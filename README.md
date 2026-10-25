# Footy Cheat

GNOME AFL tipping app. It keeps a local copy of the public [Squiggle API](https://api.squiggle.com.au/) and rates the computer models against the results. The window is a GTK 4 and libadwaita application. The tip on each game is the majority of the models.

## Requirements

Python 3.11 or newer, plus GTK 4, libadwaita, and PyGObject. On Fedora those packages are `python3`, `python3-gobject`, `gtk4`, and `libadwaita`.

## Run it

From this directory:

```bash
python -m footy_cheat
```

An install also provides the `footy-cheat` command, the desktop file, the icon, and the AppStream metainfo. The application id is `io.github.kakwit.FootyCheat`.

```bash
pip install .
footy-cheat
```

The database is created at `~/.local/share/footy-cheat/footy.db`.

The first launch downloads every Squiggle season from 2017 onward, one request at a time, with a progress screen. Later launches refresh the current season when the copy is more than 15 minutes old during the season, or check once a day for next year's fixture when the season is over. Use Update now in the header or in Preferences to refresh immediately. The button’s tooltip says when the library was last synced, and on a narrow window that time also sits beside the button. Download again replaces the local copy from 2017 onward, after a confirmation. Stop takes effect between requests; what has already been saved is kept.

Put a contact email in Preferences, from the main menu. Squiggle asks clients to send one in the User-Agent, and it is only sent to Squiggle.

## What it stores

Games, tips, sources, team logos, and the ladder from the 2017 season onward. The first season is `FIRST_SEASON_YEAR` in `footy_cheat/engine/cutoff.py`. Seasons before that are not requested. If a local database already contains them, they are deleted the next time the library opens. Squiggle's Aggregate is left out, because it only repeats the other models. Power rankings and projected ladders are not downloaded; the tipping model does not use them.

Logos are downloaded with the club list, including on a later update, so a club Squiggle adds after this release gets a crest without replacing the whole library. The PNG files under `footy_cheat/assets/logos/` are the current eighteen Squiggle crests, used when that download has not arrived yet. They are club trademarks and are not covered by the GPL. See the `NOTICE` beside them. Tasmania is not in that set. The accent colours already reserve club 19 for Tasmania; the crest itself is whatever Squiggle serves when the club appears.

## How a tip is made

The tip is the majority of models on that game. When the models are level, the side that states more confidence is the tip. If the count and the stated confidence are both level, the side whose models have the stronger records so far is the lean. If those records are level too, there is no tip.

The confidence figure is how often a vote of that strength has been right, using only games that had already been played. It is not the percentage printed by any one model.

## Live scores

While a game is within six hours of its start, the app follows Squiggle's event stream instead of polling. The stream is checked again each minute, including after the library has finished downloading, so a game that starts later in the day is picked up without restarting. If the stream drops, it reconnects until that six-hour window has passed. A game moving to full time, or a finished score being corrected, rates the models again.

## The window

Round, Ladder, and Models are the three pages. Round shows the fixture, the tip, and each model's pick. Ladder is the stored table, with the finals line after eighth. Models ranks the computer models for the selected season by record, upset rate, or margin error, and charts games clear of the median model.

Appearance, the Squiggle contact email, and the library actions are in Preferences. The accent colour can follow a club. Text size and light or dark theme are stored with the library.

| Action | Shortcut |
| --- | --- |
| Round, Ladder, Models | Ctrl+1, Ctrl+2, Ctrl+3 |
| Preferences | Ctrl+, |
| Keyboard Shortcuts | Ctrl+? |
| Previous or next round | Left, Right |
| Previous or next game | Up, Down |

On the Round page, Left and Right change the round and Up and Down change the game. They are ignored while a text field has focus.

## Flatpak

The manifest is `io.github.kakwit.FootyCheat.yml`. It uses the GNOME 51 runtime. Network access is the only permission beyond a normal window.

```bash
flatpak-builder --user --install --force-clean build-dir io.github.kakwit.FootyCheat.yml
flatpak run io.github.kakwit.FootyCheat
```

Flathub derives the repository from that id, so the metainfo points at [KAKwit/FootyCheat](https://github.com/KAKwit/FootyCheat). That repository is not published yet. Screenshots are not in the metainfo yet. Add them before submitting this to Flathub.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).

## Layout

`footy_cheat/engine/` is the library, the Squiggle parser, and the tipping model. `footy_cheat/ui/` is the window. `footy_cheat/controller.py` connects them. `data/` holds the desktop entry and the AppStream metainfo.
