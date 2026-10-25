import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from .. import APP_ID, __version__
from ..engine.cutoff import FIRST_SEASON_YEAR


def present_about(parent: Gtk.Widget) -> None:
    dialog = Adw.AboutDialog(
        application_name="Footy Cheat",
        application_icon=APP_ID,
        developer_name="↑↑↓↓←→←→BA",
        version=__version__,
        copyright="© 2026 KAKwit",
        license_type=Gtk.License.GPL_3_0,
        comments=(
            f"Footy Cheat keeps fixtures, results, ladders, and computer tips on this computer, "
            f"from the {FIRST_SEASON_YEAR} season onward. Earlier seasons are not part of the record.\n\n"
            "The tip on each game is the majority of the models. "
            "When the count is level, the side whose models state more confidence is the tip.\n\n"
            "Confidence is how often a vote of that strength has held, "
            "counted only from games that had already been played."
        ),
    )
    dialog.add_credit_section("Developer", ["KAKwit"])
    dialog.add_credit_section(None, ["Generative AI"])
    dialog.add_acknowledgement_section(
        None,
        [
            "Squiggle https://squiggle.com.au/",
            "Squiggle API https://api.squiggle.com.au/",
        ],
    )
    dialog.present(parent)


def present_shortcuts(parent: Gtk.Widget) -> None:
    dialog = Adw.ShortcutsDialog()
    general = Adw.ShortcutsSection(title="General")
    for title, accelerator in (
        ("Round", "<Control>1"),
        ("Ladder", "<Control>2"),
        ("Models", "<Control>3"),
        ("Preferences", "<Control>comma"),
        ("Keyboard Shortcuts", "<Control>question"),
    ):
        general.add(Adw.ShortcutsItem(title=title, accelerator=accelerator))
    rounds = Adw.ShortcutsSection(title="Fixture")
    for title, accelerator in (
        ("Previous round", "Left"),
        ("Next round", "Right"),
        ("Previous game", "Up"),
        ("Next game", "Down"),
    ):
        rounds.add(
            Adw.ShortcutsItem(
                title=title,
                accelerator=accelerator,
                subtitle="On the Round page, unless a text field has focus",
            )
        )
    dialog.add(general)
    dialog.add(rounds)
    dialog.present(parent)
