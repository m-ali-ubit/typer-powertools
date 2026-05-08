"""
Interactive setup wizards for guiding users through complex multi-step configurations.

Usage
-----
    from typer_powertools.input.wizard import Wizard, Step
    import typer

    app = typer.Typer()

    @app.command()
    def init():
        wizard = Wizard(
            title="Project Setup",
            steps=[
                Step("project_name", "What's your project name?"),
                Step("database", "Choose database:", choices=["postgres", "mysql", "sqlite"]),
                Step("api_key", "Enter API key:", secret=True),
                Step("port", "Server port:", default=8000, type=int),
            ]
        )
        config = wizard.run()
        save_config(config)
"""

from __future__ import annotations

import getpass
from typing import Any, Callable, Dict, List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

console = Console()


class Step:
    """A single step in a wizard.

    Parameters
    ----------
    key:
        Configuration key for this value.
    prompt:
        Question shown to the user.
    default:
        Default value (optional).
    choices:
        List of valid options (for select-style prompts).
    secret:
        If *True*, input is masked (for passwords/tokens).
    type:
        Python type for validation (int, float, str, bool).
    validator:
        Custom validation function (value -> bool or raises ValueError).
    help:
        Additional help text shown below the prompt.
    skip_if:
        Callable that receives previous answers and returns *True* to skip this step.
    """

    def __init__(
        self,
        key: str,
        prompt: str,
        default: Any = None,
        choices: Optional[List[str]] = None,
        secret: bool = False,
        type: type = str,
        validator: Optional[Callable[[Any], bool]] = None,
        help: Optional[str] = None,
        skip_if: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> None:
        self.key = key
        self.prompt = prompt
        self.default = default
        self.choices = choices
        self.secret = secret
        self.type = type
        self.validator = validator
        self.help = help
        self.skip_if = skip_if

    def should_skip(self, answers: Dict[str, Any]) -> bool:
        """Return *True* if this step should be skipped given prior answers."""
        if self.skip_if:
            return self.skip_if(answers)
        return False

    def get_input(self) -> Any:
        """Prompt the user for input according to this step's type and constraints.

        Returns
        -------
        Any
            The validated user-provided value (string, int, bool, or a choice).
        """
        if self.help:
            console.print(f"[dim]{self.help}[/dim]")

        if self.secret:
            value = getpass.getpass(f"{self.prompt} ")
            return value

        if self.choices:
            console.print(f"\n{self.prompt}")
            for i, choice in enumerate(self.choices, start=1):
                console.print(f"  {i}. {choice}")

            while True:
                try:
                    choice_input = IntPrompt.ask(
                        "Select option",
                        default=1 if self.default is None else self.choices.index(self.default) + 1,
                    )
                    if 1 <= choice_input <= len(self.choices):
                        return self.choices[choice_input - 1]
                    console.print("[red]Invalid choice. Try again.[/red]")
                except Exception:
                    console.print("[red]Invalid input. Enter a number.[/red]")

        if self.type == bool:
            return Confirm.ask(self.prompt, default=bool(self.default))

        if self.type == int:
            while True:
                try:
                    value = IntPrompt.ask(self.prompt, default=self.default)
                    if self.validator and not self.validator(value):
                        console.print("[red]Validation failed. Try again.[/red]")
                        continue
                    return value
                except Exception as exc:
                    console.print(f"[red]Invalid input: {exc}[/red]")

        while True:
            value = Prompt.ask(self.prompt, default=self.default)
            try:
                converted = self.type(value)
            except Exception as exc:
                console.print(f"[red]Invalid type: {exc}[/red]")
                continue
            if self.validator:
                try:
                    if not self.validator(converted):
                        console.print("[red]Validation failed. Try again.[/red]")
                        continue
                except ValueError as exc:
                    console.print(f"[red]{exc}[/red]")
                    continue

            return converted


class Wizard:
    """Interactive multi-step wizard for collecting user input.

    Parameters
    ----------
    title:
        Wizard title shown at the top.
    steps:
        List of Step objects defining the wizard flow.
    show_summary:
        If *True*, show a summary of answers before confirming.
    allow_back:
        If *True*, allow users to go back and edit previous answers.
    """

    def __init__(
        self,
        steps: List[Step] | None = None,
        title: str = "Setup Wizard",
        show_summary: bool = True,
        allow_back: bool = False,
    ) -> None:
        self.steps = steps or []
        self.title = title
        self.show_summary = show_summary
        self.allow_back = allow_back
        self.answers: Dict[str, Any] = {}

    def add_step(self, step: Step) -> None:
        """Append a step to the wizard."""
        self.steps.append(step)

    def run(self) -> Dict[str, Any]:
        """Execute the wizard and return a dict of collected answers.

        Iterates through each step, skipping those whose ``skip_if`` predicate
        is satisfied.  Optionally shows a summary and asks for confirmation;
        re-runs from the beginning if the user rejects and ``allow_back`` is *True*.

        Returns
        -------
        dict
            Mapping of ``step.key`` to the value supplied by the user.
        """
        console.print(Panel(Text(self.title, style="bold cyan"), expand=False))
        console.print()

        current_idx = 0
        while True:
            while current_idx < len(self.steps):
                step = self.steps[current_idx]
                if step.should_skip(self.answers):
                    current_idx += 1
                    continue
                console.print(f"[bold cyan]Step {current_idx + 1}/{len(self.steps)}[/bold cyan]")
                value = step.get_input()
                self.answers[step.key] = value
                console.print()
                current_idx += 1

            if self.show_summary:
                self._show_summary()
                confirmed = Confirm.ask("\nIs this correct?", default=True)
                if not confirmed:
                    if self.allow_back:
                        console.print("[yellow]Going back one step...[/yellow]")
                        current_idx -= 1
                        while current_idx >= 0 and self.steps[current_idx].should_skip(
                            self.answers
                        ):
                            current_idx -= 1
                        current_idx = max(0, current_idx)
                        continue
                    else:
                        raise typer.Abort()
                else:
                    break
            else:
                break

        console.print("\n[green]✓ Setup complete![/green]")
        return self.answers

    def _show_summary(self) -> None:
        """Print a summary table of all collected answers, masking secrets."""
        table = Table(title="Summary", show_header=True, show_lines=True)
        table.add_column("Setting", style="cyan bold")
        table.add_column("Value", style="green")

        for step in self.steps:
            if step.key in self.answers:
                value = self.answers[step.key]
                if step.secret:
                    display_value = "***"
                else:
                    display_value = str(value)
                table.add_row(step.prompt, display_value)

        console.print()
        console.print(table)


class WizardBuilder:
    """Fluent API for building wizards.
    Example
    -------
    ::
        wizard = (
            WizardBuilder("Project Setup")
            .ask("name", "Project name?")
            .choose("db", "Database?", ["postgres", "mysql"])
            .ask_secret("token", "API token?")
            .build()
        )
        config = wizard.run()
    """

    def __init__(self, title: str = "Setup Wizard") -> None:
        """Create a new builder with an empty step list."""
        self.title = title
        self.steps: List[Step] = []

    def ask(
        self,
        key: str,
        prompt: str,
        default: Any = None,
        type: type = str,
        help: Optional[str] = None,
    ) -> WizardBuilder:
        """Add a free-text step and return ``self`` for chaining."""
        self.steps.append(Step(key, prompt, default=default, type=type, help=help))
        return self

    def choose(
        self,
        key: str,
        prompt: str,
        choices: List[str],
        default: Optional[str] = None,
        help: Optional[str] = None,
    ) -> WizardBuilder:
        """Add a multiple-choice step and return ``self`` for chaining."""
        self.steps.append(Step(key, prompt, default=default, choices=choices, help=help))
        return self

    def ask_secret(
        self,
        key: str,
        prompt: str,
        help: Optional[str] = None,
    ) -> WizardBuilder:
        """Add a masked-input (password/token) step and return ``self`` for chaining."""
        self.steps.append(Step(key, prompt, secret=True, help=help))
        return self

    def ask_bool(
        self,
        key: str,
        prompt: str,
        default: bool = False,
        help: Optional[str] = None,
    ) -> WizardBuilder:
        """Add a yes/no confirmation step and return ``self`` for chaining."""
        self.steps.append(Step(key, prompt, default=default, type=bool, help=help))
        return self

    def ask_int(
        self,
        key: str,
        prompt: str,
        default: Optional[int] = None,
        help: Optional[str] = None,
    ) -> WizardBuilder:
        """Add an integer input step and return ``self`` for chaining."""
        self.steps.append(Step(key, prompt, default=default, type=int, help=help))
        return self

    def build(self) -> Wizard:
        """Build and return the configured :class:`Wizard` instance."""
        return Wizard(steps=self.steps, title=self.title)


def quick_wizard(
    title: str,
    questions: List[tuple[str, str] | tuple[str, str, Any]],
    show_summary: bool = True,
) -> Dict[str, Any]:
    """Quick way to run a wizard with simple text questions.

    Parameters
    ----------
    title:
        Wizard title.
    questions:
        List of (key, prompt) or (key, prompt, default) tuples.
    show_summary:
        Show summary before confirming.

    Returns
    -------
    dict
        User answers.

    Example
    -------
    ::
        config = quick_wizard(
            "Setup",
            [
                ("name", "Your name?"),
                ("age", "Your age?", 25),
                ("email", "Email address?"),
            ]
        )
    """
    steps = []
    for q in questions:
        if len(q) == 2:
            key, prompt = q
            steps.append(Step(key, prompt))
        else:
            key, prompt, default = q
            steps.append(Step(key, prompt, default=default))

    wizard = Wizard(steps=steps, title=title, show_summary=show_summary)
    return wizard.run()
