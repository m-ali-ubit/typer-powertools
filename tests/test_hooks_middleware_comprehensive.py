import time

import typer
from typer.testing import CliRunner

from typer_powertools.lifecycle.hooks import (
    ContextHookManager,
    HookManager,
    NamedHookManager,
    on_before,
)
from typer_powertools.observability.middleware import (
    Middleware,
    dry_run_middleware,
    logging_middleware,
    retry_middleware,
    timing_middleware,
    use_middleware,
    validate_middleware,
)


class TestHookManager:
    def test_before_hook_executes(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        execution_order = []

        @hooks.before
        def setup():
            execution_order.append("before")

        @app.command()
        @hooks.wrap
        def cmd():
            execution_order.append("command")

        runner.invoke(app)
        assert execution_order == ["before", "command"]

    def test_after_hook_executes(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        execution_order = []

        @hooks.after
        def cleanup():
            execution_order.append("after")

        @app.command()
        @hooks.wrap
        def cmd():
            execution_order.append("command")

        runner.invoke(app)
        assert execution_order == ["command", "after"]

    def test_both_before_and_after(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        execution_order = []

        @hooks.before
        def setup():
            execution_order.append("before")

        @hooks.after
        def cleanup():
            execution_order.append("after")

        @app.command()
        @hooks.wrap
        def cmd():
            execution_order.append("command")

        runner.invoke(app)
        assert execution_order == ["before", "command", "after"]

    def test_error_hook_on_exception(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        caught_exceptions = []

        @hooks.error
        def handle_error(exc):
            caught_exceptions.append(exc)

        @app.command()
        @hooks.wrap
        def cmd():
            raise ValueError("test error")

        runner.invoke(app)
        assert len(caught_exceptions) == 1
        assert isinstance(caught_exceptions[0], ValueError)

    def test_after_not_called_on_exception(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        execution_order = []

        @hooks.after
        def cleanup():
            execution_order.append("after")

        @app.command()
        @hooks.wrap
        def cmd():
            execution_order.append("command")
            raise ValueError("error")

        runner.invoke(app)
        assert "after" not in execution_order

    def test_finally_hook_always_runs(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        execution_order = []

        @hooks.finally_hook
        def always_run():
            execution_order.append("finally")

        @app.command()
        @hooks.wrap
        def cmd():
            execution_order.append("command")
            raise ValueError("error")

        runner.invoke(app)
        assert "finally" in execution_order

    def test_multiple_before_hooks(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        execution_order = []

        @hooks.before
        def setup1():
            execution_order.append("before1")

        @hooks.before
        def setup2():
            execution_order.append("before2")

        @app.command()
        @hooks.wrap
        def cmd():
            execution_order.append("command")

        runner.invoke(app)
        assert execution_order == ["before1", "before2", "command"]

    def test_hook_exception_doesnt_break_command(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        execution_order = []

        @hooks.before
        def failing_hook():
            raise RuntimeError("hook failed")

        @app.command()
        @hooks.wrap
        def cmd():
            execution_order.append("command")

        runner.invoke(app)
        # Command should still run despite hook failure
        assert "command" in execution_order

    def test_register_global(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        execution_order = []

        @hooks.before
        def setup():
            execution_order.append("before")

        @app.command()
        def cmd1():
            execution_order.append("cmd1")

        @app.command()
        def cmd2():
            execution_order.append("cmd2")

        hooks.register_global(app)
        runner.invoke(app, ["cmd1"])
        runner.invoke(app, ["cmd2"])
        assert execution_order == ["before", "cmd1", "before", "cmd2"]


class TestContextHookManager:
    def test_before_with_context(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = ContextHookManager()
        captured_context = []

        @hooks.before_with_context
        def log_context(ctx):
            captured_context.append(ctx)

        @app.command()
        @hooks.wrap
        def cmd(x: int = 5):
            pass

        runner.invoke(app, ["--x", "10"])
        assert len(captured_context) == 1
        assert captured_context[0]["command_name"] == "cmd"
        assert captured_context[0]["kwargs"]["x"] == 10

    def test_after_with_context(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = ContextHookManager()
        captured_data = []

        @hooks.after_with_context
        def log_result(ctx, result):
            captured_data.append((ctx, result))

        @app.command()
        @hooks.wrap
        def cmd(x: int = 5):
            return x * 2

        runner.invoke(app, ["--x", "3"])
        assert len(captured_data) == 1
        ctx, result = captured_data[0]
        assert ctx["kwargs"]["x"] == 3
        assert result == 6


class TestNamedHookManager:
    def test_command_specific_hooks(self):
        runner = CliRunner()
        app = typer.Typer()
        named_hooks = NamedHookManager()
        execution_order = []
        cmd1_hooks = named_hooks.for_command("cmd1")
        cmd2_hooks = named_hooks.for_command("cmd2")

        @cmd1_hooks.before
        def setup1():
            execution_order.append("setup1")

        @cmd2_hooks.before
        def setup2():
            execution_order.append("setup2")

        @app.command()
        @named_hooks.wrap
        def cmd1():
            execution_order.append("cmd1")

        @app.command()
        @named_hooks.wrap
        def cmd2():
            execution_order.append("cmd2")

        runner.invoke(app, ["cmd1"])
        runner.invoke(app, ["cmd2"])
        assert execution_order == ["setup1", "cmd1", "setup2", "cmd2"]


class TestModuleLevelHooks:
    def test_on_before_decorator(self):
        from typer_powertools.lifecycle.hooks import _default_manager

        _default_manager._before_hooks.clear()

        @on_before
        def setup():
            pass

        assert len(_default_manager._before_hooks) == 1


class TestMiddlewarePipeline:
    def test_single_middleware(self):
        runner = CliRunner()
        app = typer.Typer()
        execution_order = []

        def mw(next_fn, *args, **kwargs):
            execution_order.append("mw_before")
            result = next_fn(*args, **kwargs)
            execution_order.append("mw_after")
            return result

        @app.command()
        @use_middleware([mw])
        def cmd():
            execution_order.append("command")

        runner.invoke(app)
        assert execution_order == ["mw_before", "command", "mw_after"]

    def test_multiple_middleware_order(self):
        runner = CliRunner()
        app = typer.Typer()
        execution_order = []

        def mw1(next_fn, *args, **kwargs):
            execution_order.append("mw1_before")
            result = next_fn(*args, **kwargs)
            execution_order.append("mw1_after")
            return result

        def mw2(next_fn, *args, **kwargs):
            execution_order.append("mw2_before")
            result = next_fn(*args, **kwargs)
            execution_order.append("mw2_after")
            return result

        def mw3(next_fn, *args, **kwargs):
            execution_order.append("mw3_before")
            result = next_fn(*args, **kwargs)
            execution_order.append("mw3_after")
            return result

        @app.command()
        @use_middleware([mw1, mw2, mw3])
        def cmd():
            execution_order.append("command")

        runner.invoke(app)

        # Middleware runs outermost to innermost, then innermost to outermost
        expected = [
            "mw1_before",
            "mw2_before",
            "mw3_before",
            "command",
            "mw3_after",
            "mw2_after",
            "mw1_after",
        ]
        assert execution_order == expected

    def test_middleware_can_modify_args(self):
        runner = CliRunner()
        app = typer.Typer()

        def add_prefix(next_fn, *args, **kwargs):
            kwargs["text"] = "prefix_" + kwargs.get("text", "")
            return next_fn(*args, **kwargs)

        @app.command()
        @use_middleware([add_prefix])
        def cmd(text: str = ""):
            typer.echo(f"text={text}")

        result = runner.invoke(app, ["--text", "hello"])
        assert "text=prefix_hello" in result.output

    def test_middleware_can_short_circuit(self):
        runner = CliRunner()
        app = typer.Typer()
        execution_order = []

        def blocking_mw(next_fn, *args, **kwargs):
            execution_order.append("blocking")
            return "blocked"  # Don't call next_fn

        @app.command()
        @use_middleware([blocking_mw])
        def cmd():
            execution_order.append("command")

        runner.invoke(app)
        assert "blocking" in execution_order
        assert "command" not in execution_order

    def test_middleware_handles_exceptions(self):
        runner = CliRunner()
        app = typer.Typer()
        caught = []

        def error_handler(next_fn, *args, **kwargs):
            try:
                return next_fn(*args, **kwargs)
            except ValueError as e:
                caught.append(e)
                return "handled"

        @app.command()
        @use_middleware([error_handler])
        def cmd():
            raise ValueError("test")

        result = runner.invoke(app)
        assert len(caught) == 1
        assert result.exit_code == 0


class TestBuiltinMiddleware:
    def test_timing_middleware(self):
        runner = CliRunner()
        app = typer.Typer()

        @app.command()
        @use_middleware([timing_middleware(verbose=True)])
        def cmd():
            time.sleep(0.01)

        result = runner.invoke(app)
        # Should output timing info
        assert "ms" in result.output.lower() or "⏱" in result.output

    def test_timing_middleware_threshold(self):
        runner = CliRunner()
        app = typer.Typer()

        @app.command()
        @use_middleware([timing_middleware(threshold_ms=10000, verbose=False)])
        def cmd():
            time.sleep(0.001)

        result = runner.invoke(app)
        # Should not output timing (below threshold)
        assert "ms" not in result.output.lower()

    def test_retry_middleware_success(self):
        runner = CliRunner()
        app = typer.Typer()
        call_count = [0]

        @app.command()
        @use_middleware([retry_middleware(max_retries=3, delay=0.01)])
        def cmd():
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("fail")
            typer.echo("success")

        result = runner.invoke(app)
        assert call_count[0] == 3
        assert "success" in result.output

    def test_retry_middleware_exhausted(self):
        runner = CliRunner()
        app = typer.Typer()
        call_count = [0]

        @app.command()
        @use_middleware([retry_middleware(max_retries=2, delay=0.01)])
        def cmd():
            call_count[0] += 1
            raise RuntimeError("always fails")

        runner.invoke(app)
        assert call_count[0] == 3  # Initial + 2 retries

    def test_logging_middleware(self):
        runner = CliRunner()
        app = typer.Typer()

        @app.command()
        @use_middleware([logging_middleware(log_args=True, log_result=True)])
        def cmd(x: int = 5):
            return x * 2

        result = runner.invoke(app, ["--x", "3"])
        assert "→" in result.output or "cmd" in result.output

    def test_validate_middleware(self):
        runner = CliRunner()
        app = typer.Typer()

        def check_positive(kwargs):
            if kwargs.get("x", 0) < 0:
                return "x must be positive"
            return None

        @app.command()
        @use_middleware([validate_middleware(check_positive)])
        def cmd(x: int = 0):
            typer.echo(f"x={x}")

        result_fail = runner.invoke(app, ["--x", "-5"])
        assert result_fail.exit_code == 1

        result_ok = runner.invoke(app, ["--x", "5"])
        assert result_ok.exit_code == 0

    def test_dry_run_middleware(self):
        runner = CliRunner()
        app = typer.Typer()
        execution_order = []

        @app.command()
        @use_middleware([dry_run_middleware()])
        def cmd(dry_run: bool = False):
            execution_order.append("command")

        # With dry-run
        runner.invoke(app, ["--dry-run"])
        assert len(execution_order) == 0

        # Without dry-run
        runner.invoke(app, ["--no-dry-run"])
        assert len(execution_order) == 1


class TestMiddlewareClass:
    """Test class-based Middleware."""

    def test_middleware_subclass(self):
        runner = CliRunner()
        app = typer.Typer()
        execution_order = []

        class CustomMiddleware(Middleware):
            def process(self, next_fn, *args, **kwargs):
                execution_order.append("custom_before")
                result = next_fn(*args, **kwargs)
                execution_order.append("custom_after")
                return result

        @app.command()
        @use_middleware([CustomMiddleware()])
        def cmd():
            execution_order.append("command")

        runner.invoke(app)
        assert execution_order == ["custom_before", "command", "custom_after"]

    def test_middleware_with_state(self):
        runner = CliRunner()
        app = typer.Typer()

        class CountingMiddleware(Middleware):
            def __init__(self):
                self.count = 0

            def process(self, next_fn, *args, **kwargs):
                self.count += 1
                return next_fn(*args, **kwargs)

        counter = CountingMiddleware()

        @app.command()
        @use_middleware([counter])
        def cmd():
            typer.echo(f"count={counter.count}")

        result = runner.invoke(app)
        assert "count=1" in result.output


class TestEdgeCases:
    def test_empty_middleware_list(self):
        runner = CliRunner()
        app = typer.Typer()

        @app.command()
        @use_middleware([])
        def cmd():
            typer.echo("ok")

        result = runner.invoke(app)
        assert "ok" in result.output

    def test_middleware_exception_propagates(self):
        runner = CliRunner()
        app = typer.Typer()

        def failing_mw(next_fn, *args, **kwargs):
            raise RuntimeError("middleware error")

        @app.command()
        @use_middleware([failing_mw])
        def cmd():
            pass

        result = runner.invoke(app)
        assert result.exit_code != 0

    def test_nested_middleware_stacks(self):
        runner = CliRunner()
        app = typer.Typer()
        execution_order = []

        def mw1(next_fn, *args, **kwargs):
            execution_order.append("1")
            return next_fn(*args, **kwargs)

        def mw2(next_fn, *args, **kwargs):
            execution_order.append("2")
            return next_fn(*args, **kwargs)

        @app.command()
        @use_middleware([mw1])
        @use_middleware([mw2])
        def cmd():
            execution_order.append("cmd")

        runner.invoke(app)
        # Both middleware should run
        assert "1" in execution_order
        assert "2" in execution_order
        assert "cmd" in execution_order
