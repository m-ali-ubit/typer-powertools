"""
File and project generation from Jinja2 templates (like cookiecutter).

Usage
-----
    from typer_powertools.extensibility.templates import TemplateEngine, render_template
    import typer

    app = typer.Typer()

    @app.command()
    def new(project_name: str, project_type: str = "api"):
        render_template(
            template_dir=f"templates/{project_type}/",
            output_dir=f"./{project_name}/",
            context={
                "project_name": project_name,
                "author": "Your Name",
            }
        )

Template Structure
------------------
    templates/
        api/
            {{project_name}}/
                __init__.py.j2
                main.py.j2
                config.json.j2
                README.md.j2

Template files use Jinja2 syntax:
    # main.py.j2
    def main():
        print("Welcome to {{ project_name }}!")

Directory names can also use Jinja2:
    {{ project_name }}/
    {{ module_name }}/
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import track

console = Console()

try:
    from jinja2 import Environment, FileSystemLoader, Template, TemplateError

    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False


class TemplateEngine:
    def __init__(
        self,
        template_dir: Path | str,
        output_dir: Path | str,
        context: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> None:
        """
        Parameters
        ----------
        template_dir:
            Directory containing template files.
        output_dir:
            Directory where rendered files will be written.
        context:
            Variables available in templates.
        overwrite:
            If *True*, overwrite existing files.
        """
        if not _JINJA2_AVAILABLE:
            raise ImportError(
                "jinja2 is required for templates. Install with: "
                "pip install 'typer-powertools[templates]'"
            )

        self.template_dir = Path(template_dir).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.context = context or {}
        self.overwrite = overwrite

        if not self.template_dir.exists():
            raise FileNotFoundError(f"Template directory not found: {self.template_dir}")

        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=False,
        )

    def render_path(self, path: str) -> str:
        """Render a path string with Jinja2 (for dynamic directory/file names)."""
        template = Template(path)
        return template.render(**self.context)

    def render_file(self, template_path: Path) -> str:
        """Render a template file and return the result as a string.

        Parameters
        ----------
        template_path:
            Absolute path to the ``.j2`` template file inside ``template_dir``.

        Returns
        -------
        str
            Rendered content.
        """
        relative_path = template_path.relative_to(self.template_dir)
        template = self.env.get_template(str(relative_path))
        return template.render(**self.context)

    def process_file(self, template_path: Path) -> Optional[Path]:
        """Render a single template file and write it to ``output_dir``.

        Skips the file if the output already exists and ``overwrite`` is *False*.

        Parameters
        ----------
        template_path:
            Absolute path to the template file.

        Returns
        -------
        Path | None
            Path of the created output file, or *None* if skipped/failed.
        """
        rel_path = template_path.relative_to(self.template_dir)
        rendered_rel_path = self.render_path(str(rel_path))
        if rendered_rel_path.endswith(".j2"):
            rendered_rel_path = rendered_rel_path[:-3]
        output_path = self.output_dir / rendered_rel_path

        if output_path.exists() and not self.overwrite:
            console.print(f"[yellow]⊗ Skipped (exists): {output_path}[/yellow]")
            return None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = self.render_file(template_path)
            output_path.write_text(content, encoding="utf-8")
            console.print(f"[green]✓[/green] Created: [cyan]{output_path}[/cyan]")
            return output_path
        except TemplateError as exc:
            console.print(f"[red]✗ Template error in {template_path}: {exc}[/red]")
            return None
        except Exception as exc:
            console.print(f"[red]✗ Failed to create {output_path}: {exc}[/red]")
            return None

    def render_all(self) -> List[Path]:
        """Render every template file in ``template_dir`` to ``output_dir``.

        Returns
        -------
        list[Path]
            Paths of all successfully created output files.
        """
        created_files: List[Path] = []
        template_files = list(self.template_dir.rglob("*"))
        template_files = [f for f in template_files if f.is_file()]

        console.print(
            Panel(
                f"[bold]Rendering {len(template_files)} templates[/bold]\n"
                f"From: [cyan]{self.template_dir}[/cyan]\n"
                f"To:   [cyan]{self.output_dir}[/cyan]",
                expand=False,
            )
        )
        console.print()

        for template_file in track(template_files, description="Rendering…"):
            result = self.process_file(template_file)
            if result:
                created_files.append(result)

        console.print()
        console.print(f"[green]✓ Created {len(created_files)} files[/green]")
        return created_files


def render_template(
    template_dir: Path | str,
    output_dir: Path | str,
    context: Optional[Dict[str, Any]] = None,
    overwrite: bool = False,
) -> List[Path]:
    """Render all templates in a directory.

    Parameters
    ----------
    template_dir:
        Directory containing template files.
    output_dir:
        Directory where rendered files will be written.
    context:
        Variables available in templates.
    overwrite:
        If *True*, overwrite existing files.

    Returns
    -------
    list[Path]
        Paths to created files.

    Example
    -------
    ::

        render_template(
            template_dir="templates/fastapi/",
            output_dir="./my-project/",
            context={"project_name": "my-project", "author": "Alice"}
        )
    """
    engine = TemplateEngine(
        template_dir=template_dir,
        output_dir=output_dir,
        context=context,
        overwrite=overwrite,
    )
    return engine.render_all()


def render_single_file(
    template_file: Path | str,
    output_file: Path | str,
    context: Optional[Dict[str, Any]] = None,
    overwrite: bool = False,
) -> Optional[Path]:
    """Render a single template file.

    Parameters
    ----------
    template_file:
        Path to the template file.
    output_file:
        Path where the rendered file will be written.
    context:
        Variables available in template.
    overwrite:
        If *True*, overwrite existing file.

    Returns
    -------
    Path | None
        Path to created file, or *None* if skipped/failed.
    """
    if not _JINJA2_AVAILABLE:
        raise ImportError(
            "jinja2 is required for templates. Install with: "
            "pip install 'typer-powertools[templates]'"
        )

    template_path = Path(template_file)
    output_path = Path(output_file)

    if not template_path.exists():
        console.print(f"[red]✗ Template not found: {template_path}[/red]")
        return None

    if output_path.exists() and not overwrite:
        console.print(f"[yellow]⊗ Output file exists: {output_path}[/yellow]")
        return None

    try:
        env = Environment(autoescape=False)
        template = env.from_string(template_path.read_text(encoding="utf-8"))
        rendered = template.render(**(context or {}))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

        console.print(f"[green]✓ Created: {output_path}[/green]")
        return output_path
    except Exception as exc:
        console.print(f"[red]✗ Failed to render: {exc}[/red]")
        return None


class TemplateRepository:
    """Manages multiple named templates (like cookiecutter templates).

    Example
    -------
    ::

        repo = TemplateRepository("~/.myapp/templates/")
        repo.register("api", "templates/fastapi-template/")
        repo.register("cli", "templates/typer-template/")

        # Use a template
        repo.use("api", output_dir="./my-api/", context={"name": "my-api"})
    """

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.templates: Dict[str, Path] = {}

    def register(self, name: str, template_path: Path | str) -> None:
        """Register a named template by pointing to its directory.

        Parameters
        ----------
        name:
            Logical name used to reference this template (e.g. ``"api"``).
        template_path:
            Path to the template directory. Relative paths are resolved
            against ``base_dir``.
        """
        path = Path(template_path)
        if not path.is_absolute():
            path = self.base_dir / path
        self.templates[name] = path

    def list_templates(self) -> List[str]:
        """Return the names of all registered templates."""
        return list(self.templates.keys())

    def get_template_path(self, name: str) -> Optional[Path]:
        """Return the directory path for a registered template, or *None* if not found."""
        return self.templates.get(name)

    def use(
        self,
        template_name: str,
        output_dir: Path | str,
        context: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> Optional[List[Path]]:
        """Use a registered template to generate files.

        Parameters
        ----------
        template_name:
            Name of the registered template.
        output_dir:
            Where to generate files.
        context:
            Template variables.
        overwrite:
            Whether to overwrite existing files.

        Returns
        -------
        list[Path] | None
            List of created files, or *None* if template not found.
        """
        template_path = self.get_template_path(template_name)
        if not template_path:
            console.print(f"[red]✗ Template not found: {template_name}[/red]")
            console.print(f"[dim]Available: {', '.join(self.list_templates())}[/dim]")
            return None

        return render_template(
            template_dir=template_path,
            output_dir=output_dir,
            context=context,
            overwrite=overwrite,
        )
