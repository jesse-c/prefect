"""
Unit tests for PrefectDbtRunner - focusing on outcomes.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest
from dbt.artifacts.resources.types import NodeType
from dbt.artifacts.schemas.results import RunStatus
from dbt.artifacts.schemas.run import RunExecutionResult
from dbt.contracts.graph.manifest import Manifest
from dbt.contracts.graph.nodes import ManifestNode
from dbt_common.events.base_types import EventLevel, EventMsg
from prefect_dbt.core.runner import PrefectDbtRunner, execute_dbt_node
from prefect_dbt.core.settings import PrefectDbtSettings


class TestPrefectDbtRunner:
    """Test cases focusing on PrefectDbtRunner outcomes and behavior."""

    def test_runner_initializes_with_working_configuration(self):
        """Test that runner initializes with a working configuration."""
        runner = PrefectDbtRunner()

        # Verify runner has all required components
        assert runner.settings is not None
        assert isinstance(runner.settings, PrefectDbtSettings)
        assert runner.raise_on_failure is True
        assert runner.client is not None

    def test_runner_accepts_custom_configuration(self):
        """Test that runner accepts and uses custom configuration."""
        custom_settings = PrefectDbtSettings()
        custom_manifest = Mock(spec=Manifest)
        custom_client = Mock()

        runner = PrefectDbtRunner(
            manifest=custom_manifest,
            settings=custom_settings,
            raise_on_failure=False,
            client=custom_client,
            include_compiled_code=True,
        )

        # Verify custom configuration is used
        assert runner.settings == custom_settings
        assert runner.raise_on_failure is False
        assert runner.client == custom_client
        assert runner.include_compiled_code is True

    def test_runner_handles_manifest_loading_successfully(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that runner can load manifest successfully."""
        mock_manifest = Mock(spec=Manifest)

        # Mock file operations
        mock_open = Mock()
        mock_open.return_value.__enter__ = Mock(return_value=Mock())
        mock_open.return_value.__exit__ = Mock(return_value=None)

        monkeypatch.setattr("builtins.open", mock_open)
        monkeypatch.setattr("json.load", Mock(return_value={"test": "data"}))
        monkeypatch.setattr(Manifest, "from_dict", Mock(return_value=mock_manifest))

        runner = PrefectDbtRunner()
        runner._target_path = Path("target")
        runner._project_dir = Path("/test/project")

        # Access manifest property to trigger loading
        result = runner.manifest

        assert result == mock_manifest

    def test_runner_handles_manifest_file_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that runner handles missing manifest file gracefully."""
        monkeypatch.setattr("builtins.open", Mock(side_effect=FileNotFoundError()))

        runner = PrefectDbtRunner()
        runner._target_path = Path("target")
        runner._project_dir = Path("/test/project")

        with pytest.raises(ValueError, match="Manifest file not found"):
            _ = runner.manifest

    def test_runner_processes_dbt_events_correctly(self):
        """Test that runner processes dbt events correctly."""
        event = Mock(spec=EventMsg)
        event.info = Mock()
        event.info.msg = "Test dbt event message"

        result = PrefectDbtRunner.get_dbt_event_msg(event)
        assert result == "Test dbt event message"

    def test_runner_extracts_node_id_from_events(self):
        """Test that runner extracts node IDs from dbt events."""
        runner = PrefectDbtRunner()

        event = Mock(spec=EventMsg)
        event.data = Mock()
        event.data.node_info = Mock()
        event.data.node_info.unique_id = "test_node_id"

        result = runner._get_dbt_event_node_id(event)
        assert result == "test_node_id"

    def test_runner_handles_cli_argument_parsing(self):
        """Test that runner handles CLI argument parsing correctly."""
        runner = PrefectDbtRunner()

        # Test extracting flag values
        args = ["--target-path", "/custom/path", "run"]
        result_args, value = runner._extract_flag_value(args, "--target-path")

        assert result_args == ["run"]
        assert value == "/custom/path"

        # Test handling missing flags
        args = ["run"]
        result_args, value = runner._extract_flag_value(args, "--target-path")

        assert result_args == ["run"]
        assert value is None

    def test_runner_updates_settings_from_kwargs(self):
        """Test that runner updates settings from kwargs."""
        runner = PrefectDbtRunner()
        kwargs = {"target_path": "/custom/path"}

        runner._update_setting_from_kwargs("target_path", kwargs)

        assert runner._target_path == "/custom/path"
        assert "target_path" not in kwargs  # Should be removed

    def test_runner_updates_settings_from_cli_flags(self):
        """Test that runner updates settings from CLI flags."""
        runner = PrefectDbtRunner()
        args = ["--target-path", "/custom/path", "run"]

        result_args = runner._update_setting_from_cli_flag(
            args, "--target-path", "target_path", Path
        )

        assert result_args == ["run"]
        assert runner._target_path == Path("/custom/path")

    def test_runner_invokes_dbt_successfully(self, monkeypatch: pytest.MonkeyPatch):
        """Test that runner invokes dbt commands successfully."""
        runner = PrefectDbtRunner()

        mock_result = Mock()
        mock_result.success = True
        mock_result.exception = None

        mock_dbt_runner_instance = Mock()
        mock_dbt_runner_instance.invoke.return_value = mock_result

        monkeypatch.setattr(
            "prefect_dbt.core.runner.dbtRunner",
            Mock(return_value=mock_dbt_runner_instance),
        )

        # Mock the callback methods
        monkeypatch.setattr(runner, "_create_logging_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_started_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_finished_callback", Mock())

        result = runner.invoke(["run"])

        assert result == mock_result
        mock_dbt_runner_instance.invoke.assert_called_once()

    def test_runner_handles_dbt_exceptions(self, monkeypatch: pytest.MonkeyPatch):
        """Test that runner handles dbt exceptions gracefully."""
        runner = PrefectDbtRunner()

        mock_result = Mock()
        mock_result.success = False
        mock_result.exception = "Test exception"

        mock_dbt_runner_instance = Mock()
        mock_dbt_runner_instance.invoke.return_value = mock_result

        monkeypatch.setattr(
            "prefect_dbt.core.runner.dbtRunner",
            Mock(return_value=mock_dbt_runner_instance),
        )

        # Mock the callback methods
        monkeypatch.setattr(runner, "_create_logging_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_started_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_finished_callback", Mock())

        with pytest.raises(ValueError, match="Failed to invoke dbt command"):
            runner.invoke(["run"])

    def test_runner_handles_dbt_failures_with_raise_on_failure_true(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that runner raises on dbt failures when raise_on_failure is True."""
        runner = PrefectDbtRunner(raise_on_failure=True)

        mock_result = Mock()
        mock_result.success = False
        mock_result.exception = None
        mock_result.result = Mock(spec=RunExecutionResult)
        mock_result.result.results = [
            Mock(
                status=RunStatus.Error,
                node=Mock(resource_type="model", name="test_model"),
                message="Test error",
            )
        ]

        mock_dbt_runner_instance = Mock()
        mock_dbt_runner_instance.invoke.return_value = mock_result

        monkeypatch.setattr(
            "prefect_dbt.core.runner.dbtRunner",
            Mock(return_value=mock_dbt_runner_instance),
        )

        # Mock the callback methods
        monkeypatch.setattr(runner, "_create_logging_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_started_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_finished_callback", Mock())

        with pytest.raises(ValueError, match="Failures detected during invocation"):
            runner.invoke(["run"])

    def test_runner_handles_dbt_failures_with_raise_on_failure_false(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that runner doesn't raise on dbt failures when raise_on_failure is False."""
        runner = PrefectDbtRunner(raise_on_failure=False)

        mock_result = Mock()
        mock_result.success = False
        mock_result.exception = None
        mock_result.result = Mock(spec=RunExecutionResult)
        mock_result.result.results = [
            Mock(
                status=RunStatus.Error,
                node=Mock(resource_type="model", name="test_model"),
                message="Test error",
            )
        ]

        mock_dbt_runner_instance = Mock()
        mock_dbt_runner_instance.invoke.return_value = mock_result

        monkeypatch.setattr(
            "prefect_dbt.core.runner.dbtRunner",
            Mock(return_value=mock_dbt_runner_instance),
        )

        # Mock the callback methods
        monkeypatch.setattr(runner, "_create_logging_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_started_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_finished_callback", Mock())

        result = runner.invoke(["run"])
        assert result == mock_result

    def test_runner_creates_callbacks_successfully(self):
        """Test that runner creates all required callbacks successfully."""
        runner = PrefectDbtRunner()
        task_state = Mock()
        context = {"test": "context"}
        log_level = EventLevel.INFO

        # Test logging callback creation
        logging_callback = runner._create_logging_callback(
            task_state, log_level, context
        )
        assert callable(logging_callback)

        # Test node started callback creation
        node_started_callback = runner._create_node_started_callback(
            task_state, context
        )
        assert callable(node_started_callback)

        # Test node finished callback creation
        node_finished_callback = runner._create_node_finished_callback(task_state)
        assert callable(node_finished_callback)

    def test_runner_handles_kwargs_and_cli_flags_together(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that runner handles both kwargs and CLI flags together."""
        runner = PrefectDbtRunner()

        mock_result = Mock()
        mock_result.success = True
        mock_result.exception = None

        mock_dbt_runner_instance = Mock()
        mock_dbt_runner_instance.invoke.return_value = mock_result

        monkeypatch.setattr(
            "prefect_dbt.core.runner.dbtRunner",
            Mock(return_value=mock_dbt_runner_instance),
        )

        # Mock the callback methods
        monkeypatch.setattr(runner, "_create_logging_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_started_callback", Mock())
        monkeypatch.setattr(runner, "_create_node_finished_callback", Mock())

        # Test with both kwargs and CLI flags
        result = runner.invoke(
            ["--target-path", "/cli/path", "run"], target_path="/kwargs/path"
        )

        assert result == mock_result
        # CLI flag should take precedence
        assert runner._target_path == Path("/cli/path")

    def test_get_upstream_manifest_nodes_and_configs_returns_correct_structure(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that _get_upstream_manifest_nodes_and_configs returns correct structure."""
        runner = PrefectDbtRunner()

        # Mock manifest and nodes
        mock_manifest = Mock(spec=Manifest)

        # Create properly configured mock nodes
        mock_node_1 = Mock(spec=ManifestNode)
        mock_node_1.relation_name = "test_relation_1"
        mock_node_1.config = Mock()
        mock_node_1.config.meta = {"prefect": {"enable_assets": True}}

        mock_node_2 = Mock(spec=ManifestNode)
        mock_node_2.relation_name = "test_relation_2"
        mock_node_2.config = Mock()
        mock_node_2.config.meta = {"prefect": {"enable_assets": False}}

        mock_manifest.nodes = {
            "upstream_node_1": mock_node_1,
            "upstream_node_2": mock_node_2,
        }

        runner._manifest = mock_manifest

        # Create a mock manifest node with dependencies
        mock_node = Mock(spec=ManifestNode)
        mock_node.depends_on_nodes = ["upstream_node_1", "upstream_node_2"]

        result = runner._get_upstream_manifest_nodes_and_configs(mock_node)

        # Verify structure: list of tuples (ManifestNode, dict)
        assert isinstance(result, list)
        assert len(result) == 2

        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], Mock)  # ManifestNode
            assert isinstance(item[1], dict)  # config dict

    def test_get_upstream_manifest_nodes_and_configs_handles_missing_nodes(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that _get_upstream_manifest_nodes_and_configs handles missing nodes gracefully."""
        runner = PrefectDbtRunner()

        # Mock manifest with missing nodes
        mock_manifest = Mock(spec=Manifest)
        mock_manifest.nodes = {}  # Empty nodes dict
        runner._manifest = mock_manifest

        # Create a mock manifest node with dependencies
        mock_node = Mock(spec=ManifestNode)
        mock_node.depends_on_nodes = ["missing_node_1", "missing_node_2"]

        result = runner._get_upstream_manifest_nodes_and_configs(mock_node)

        # Should return empty list when nodes are missing
        assert result == []

    def test_get_upstream_manifest_nodes_and_configs_handles_missing_relation_name(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that _get_upstream_manifest_nodes_and_configs handles missing relation_name."""
        runner = PrefectDbtRunner()

        # Mock manifest and nodes
        mock_manifest = Mock(spec=Manifest)
        mock_node_without_relation = Mock(spec=ManifestNode)
        mock_node_without_relation.relation_name = None  # Missing relation_name
        mock_node_without_relation.config = Mock()
        mock_node_without_relation.config.meta = {}
        mock_manifest.nodes = {"upstream_node": mock_node_without_relation}
        runner._manifest = mock_manifest

        # Create a mock manifest node with dependencies
        mock_node = Mock(spec=ManifestNode)
        mock_node.depends_on_nodes = ["upstream_node"]

        with pytest.raises(ValueError, match="Relation name not found in manifest"):
            runner._get_upstream_manifest_nodes_and_configs(mock_node)

    def test_call_task_with_enable_assets_true_creates_materializing_task(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that _call_task creates MaterializingTask when enable_assets is True."""
        runner = PrefectDbtRunner()

        # Mock manifest with adapter type
        mock_manifest = Mock(spec=Manifest)
        mock_manifest.metadata = Mock()
        mock_manifest.metadata.adapter_type = "snowflake"
        mock_manifest.nodes = {}
        runner._manifest = mock_manifest

        # Mock manifest node
        mock_node = Mock(spec=ManifestNode)
        mock_node.resource_type = NodeType.Model
        mock_node.unique_id = "test_node"
        mock_node.relation_name = "test_relation"
        mock_node.name = "test_model"
        mock_node.description = "Test model"
        mock_node.config = Mock()
        mock_node.config.meta = {}

        # Mock task state
        mock_task_state = Mock()

        # Mock the upstream nodes method to return empty list
        monkeypatch.setattr(
            runner, "_get_upstream_manifest_nodes_and_configs", Mock(return_value=[])
        )

        # Mock task creation methods
        mock_asset = Mock()
        monkeypatch.setattr(
            runner, "_create_asset_from_node", Mock(return_value=mock_asset)
        )
        mock_task_options = {"task_run_name": "test_task", "cache_policy": Mock()}
        monkeypatch.setattr(
            runner, "_create_task_options", Mock(return_value=mock_task_options)
        )

        # Mock MaterializingTask creation
        mock_materializing_task = Mock()
        monkeypatch.setattr(
            "prefect_dbt.core.runner.MaterializingTask",
            Mock(return_value=mock_materializing_task),
        )

        # Mock format_resource_id
        monkeypatch.setattr(
            "prefect_dbt.core.runner.format_resource_id",
            Mock(return_value="test_asset_id"),
        )

        context = {"test": "context"}
        enable_assets = True

        runner._call_task(mock_task_state, mock_node, context, enable_assets)

        # Verify MaterializingTask was created and started
        mock_task_state.start_task.assert_called_once_with(
            "test_node", mock_materializing_task
        )
        mock_task_state.set_node_dependencies.assert_called_once_with("test_node", [])
        mock_task_state.run_task_in_thread.assert_called_once()

    def test_call_task_with_enable_assets_false_creates_regular_task(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that _call_task creates regular Task when enable_assets is False."""
        runner = PrefectDbtRunner()

        # Mock manifest with adapter type
        mock_manifest = Mock(spec=Manifest)
        mock_manifest.metadata = Mock()
        mock_manifest.metadata.adapter_type = "snowflake"
        mock_manifest.nodes = {}
        runner._manifest = mock_manifest

        # Mock manifest node
        mock_node = Mock(spec=ManifestNode)
        mock_node.resource_type = NodeType.Model
        mock_node.unique_id = "test_node"
        mock_node.relation_name = "test_relation"
        mock_node.name = "test_model"
        mock_node.description = "Test model"
        mock_node.config = Mock()
        mock_node.config.meta = {}

        # Mock task state
        mock_task_state = Mock()

        # Mock the upstream nodes method to return empty list
        monkeypatch.setattr(
            runner, "_get_upstream_manifest_nodes_and_configs", Mock(return_value=[])
        )

        # Mock task creation methods
        mock_task_options = {"task_run_name": "test_task", "cache_policy": Mock()}
        monkeypatch.setattr(
            runner, "_create_task_options", Mock(return_value=mock_task_options)
        )

        # Mock Task creation
        mock_task = Mock()
        monkeypatch.setattr(
            "prefect_dbt.core.runner.Task", Mock(return_value=mock_task)
        )

        context = {"test": "context"}
        enable_assets = False

        runner._call_task(mock_task_state, mock_node, context, enable_assets)

        # Verify regular Task was created and started
        mock_task_state.start_task.assert_called_once_with("test_node", mock_task)
        mock_task_state.set_node_dependencies.assert_called_once_with("test_node", [])
        mock_task_state.run_task_in_thread.assert_called_once()

    def test_call_task_handles_missing_adapter_type(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that _call_task handles missing adapter type gracefully."""
        runner = PrefectDbtRunner()

        # Mock manifest without adapter type
        mock_manifest = Mock(spec=Manifest)
        mock_manifest.metadata = Mock()
        mock_manifest.metadata.adapter_type = None
        runner._manifest = mock_manifest

        # Mock manifest node
        mock_node = Mock(spec=ManifestNode)
        mock_node.resource_type = NodeType.Model

        # Mock task state
        mock_task_state = Mock()

        context = {"test": "context"}
        enable_assets = True

        with pytest.raises(ValueError, match="Adapter type not found in manifest"):
            runner._call_task(mock_task_state, mock_node, context, enable_assets)

    def test_call_task_handles_missing_relation_name_for_assets(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that _call_task handles missing relation_name when creating assets."""
        runner = PrefectDbtRunner()

        # Mock manifest with adapter type
        mock_manifest = Mock(spec=Manifest)
        mock_manifest.metadata = Mock()
        mock_manifest.metadata.adapter_type = "snowflake"
        mock_manifest.nodes = {}
        runner._manifest = mock_manifest

        # Mock manifest node without relation_name
        mock_node = Mock(spec=ManifestNode)
        mock_node.resource_type = NodeType.Model
        mock_node.unique_id = "test_node"
        mock_node.relation_name = None  # Missing relation_name
        mock_node.config = Mock()
        mock_node.config.meta = {}

        # Mock task state
        mock_task_state = Mock()

        # Mock the upstream nodes method to return empty list
        monkeypatch.setattr(
            runner, "_get_upstream_manifest_nodes_and_configs", Mock(return_value=[])
        )

        context = {"test": "context"}
        enable_assets = True

        with pytest.raises(ValueError, match="Relation name not found in manifest"):
            runner._call_task(mock_task_state, mock_node, context, enable_assets)


class TestExecuteDbtNode:
    """Test cases focusing on execute_dbt_node behavior."""

    def test_execute_dbt_node_completes_successfully(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that execute_dbt_node completes successfully."""
        task_state = Mock()
        node_id = "test_node"
        asset_id = "test_asset"

        # Mock successful completion
        task_state.get_node_status.return_value = {
            "event_data": {"node_info": {"node_status": RunStatus.Success}}
        }

        mock_logger = Mock()
        monkeypatch.setattr(
            "prefect_dbt.core.runner.get_run_logger", Mock(return_value=mock_logger)
        )

        execute_dbt_node(task_state, node_id, asset_id)

        # Verify expected interactions
        task_state.set_task_logger.assert_called_once_with(node_id, mock_logger)
        task_state.wait_for_node_completion.assert_called_once_with(node_id)
        task_state.get_node_status.assert_called_once_with(node_id)

    def test_execute_dbt_node_handles_failure_status(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that execute_dbt_node handles failure status correctly."""
        task_state = Mock()
        node_id = "test_node"
        asset_id = "test_asset"

        # Mock failure status
        task_state.get_node_status.return_value = {
            "event_data": {"node_info": {"node_status": RunStatus.Error}}
        }

        monkeypatch.setattr("prefect_dbt.core.runner.get_run_logger", Mock())

        with pytest.raises(
            Exception, match="Node test_node finished with status error"
        ):
            execute_dbt_node(task_state, node_id, asset_id)

    def test_execute_dbt_node_handles_no_status(self, monkeypatch: pytest.MonkeyPatch):
        """Test that execute_dbt_node handles missing status gracefully."""
        task_state = Mock()
        node_id = "test_node"
        asset_id = "test_asset"

        # Mock no status returned
        task_state.get_node_status.return_value = None

        monkeypatch.setattr("prefect_dbt.core.runner.get_run_logger", Mock())

        execute_dbt_node(task_state, node_id, asset_id)

        # Verify function completes without error
        task_state.set_task_logger.assert_called_once()
        task_state.wait_for_node_completion.assert_called_once_with(node_id)
        task_state.get_node_status.assert_called_once_with(node_id)

    def test_execute_dbt_node_with_asset_context(self, monkeypatch: pytest.MonkeyPatch):
        """Test that execute_dbt_node works with asset context."""
        task_state = Mock()
        node_id = "test_node"
        asset_id = "test_asset"

        # Mock successful completion with node info
        node_info = {"node_status": RunStatus.Success, "name": "test_model"}
        task_state.get_node_status.return_value = {
            "event_data": {"node_info": node_info}
        }

        monkeypatch.setattr("prefect_dbt.core.runner.get_run_logger", Mock())

        mock_context = Mock()
        mock_asset_context = Mock()
        mock_asset_context.get.return_value = mock_context
        monkeypatch.setattr("prefect_dbt.core.runner.AssetContext", mock_asset_context)

        execute_dbt_node(task_state, node_id, asset_id)

        # Verify asset metadata was added
        mock_context.add_asset_metadata.assert_called_once_with(asset_id, node_info)
