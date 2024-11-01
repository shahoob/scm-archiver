import json
from pathlib import Path
import time
from typing import Annotated, Optional
import requests
import typer
from alive_progress import alive_bar
from pydantic import BaseModel

app = typer.Typer()

def default_path_factory() -> Path:
    return Path.cwd() / "archive"

class Game(BaseModel):
    name: str
    id: int
    has_game_banner: bool
    songs: list["Song"] = []

class Song(BaseModel):
    name: str
    id: int
    uploader: str
    remix: bool | None = None
    available: bool | None = None
    game_id: int
    loop: str

@app.command()
def main(
    download_path: Annotated[Path, typer.Argument(
        default_factory=default_path_factory, dir_okay=True,
        help="Path to the directory where the archive will reside."
    )],
    reuse_cached_info: Annotated[bool, typer.Option(
        "--reuse-cached-info/--dont-reuse-cached-info",
        help="Wether or not to reuse cached info when resuming.")] = False,
    use_aria2_asap: Annotated[bool, typer.Option(
        "--use-aria2-asap/--dont-use-aria2-asap",
    )] = True,
    auto_filename_aria2: Annotated[bool, typer.Option(
        "--auto-filename-aria2/--song_name-filename-aria2",
    )] = False
):
    _gamelist: dict
    gamelist: list[Game] = []
    songs: dict[int, list[Song]]

    with alive_bar(monitor=False, stats=False, title="Fetch game list") as bar:
        gamelist_path = (download_path / "gamelist.json")
        if gamelist_path.exists():
            with open(gamelist_path, "r") as f:
                _gamelist = json.load(f)
                print("Cache hit! (gamelist.json)")
        else:
            r_gamelist = requests.get("https://smashcustommusic.net/json/gamelist/")
            _gamelist = r_gamelist.json()
            gamelist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(gamelist_path, "w") as f:
                f.write(r_gamelist.text)
        bar()

    total_songs: int = 0
    game_with_banner: int = 0

    with alive_bar(_gamelist["game_count"], dual_line=True, title="Fetch game info") as bar:
        for game in _gamelist["games"]:
            bar.text = f"-> [{game['game_id']}] \"{game['game_name']}\""
            game_info_path = (download_path / str(game['game_id']) / f"data.json")
            skipped: bool = False
            fetch_file: bool = False
            if game_info_path.exists():
                with open(game_info_path, "r") as f:
                    _game = json.load(f)
                    # print(f"Cache hit! ([{game['game_id']}] {game['game_name']})")
                    if (_game["game_name"] != game["game_name"]) or (_game["track_count"] != game["song_count"]):
                        fetch_file = True
                    else:
                        skipped = True
            else:
                fetch_file = True
            if fetch_file:
                r_game = requests.get(f"https://smashcustommusic.net/json/game/{game['game_id']}")
                r_game.raise_for_status()
                _game = r_game.json()
                game_info_path.parent.mkdir(parents=True, exist_ok=True)
                with open(game_info_path, "w") as f:
                    f.write(r_game.text)

            _songs: list[Song] = []
            if "songs" in _game:
                for song in _game["songs"]:
                    _songs.append(Song(
                        id=song["song_id"], 
                        name=song["song_name"], 
                        uploader=(song["song_uploader"] if ("song_uploader" in song) and (song["song_uploader"] != None) else ""), 
                        available=song["song_available"], 
                        game_id=game["game_id"],
                        loop=(song["song_loop"] if ("song_loop" in song) else ""),
                    ))
            # if game["song_count"] == 0: print(f"[{game['game_id']}] \"{game['game_name']}\" has no songs")
            game = Game(name=_game["game_name"], id=game["game_id"], has_game_banner=bool(_game["game_banner_exists"]), songs=_songs)
            gamelist.append(game)
            bar(skipped=skipped)
    
    for game in gamelist:
        total_songs += len(game.songs)
        if game.has_game_banner:
            game_with_banner += 1

    if not use_aria2_asap:
        with alive_bar(total_songs, dual_line=True, title="Fetch song info") as bar:
            for game in gamelist:
                for i, song in enumerate(game.songs):
                    bar.text = f"-> [{game.id}] \"{game.name}\" / [{song.id}] \"{song.name}\""
                    song_info_path = (download_path / str(game.id) / str(song.id) / f"data.json")
                    skipped: bool = False
                    fetch_file: bool = False
                    if song_info_path.exists():
                        with open(song_info_path, "r") as f:
                            _song = json.load(f)
                            # print(f"Cache hit! ([{game.id}] [{song.id}] \"{song.name}\")")
                            if (_song["song_name"] != song.name) or (_song["song_uploader"] != song.uploader):
                                fetch_file = True
                            else:
                                skipped = True
                    else:
                        fetch_file = True
                    if fetch_file:
                        r_song = requests.get(f"https://smashcustommusic.net/json/song/{song.id}")
                        _song = r_song.json()
                        song_info_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(song_info_path, "w") as f:
                            f.write(r_song.text)
                    bar(skipped=skipped)

    with alive_bar(total_songs+game_with_banner, dual_line=True, title="Compile download list") as bar:
        with open(download_path / "aria2_input", "w") as f:
            for game in gamelist:
                bar.text = f"-> [{game.id}] \"{game.name}\""
                f.write(f"# {game.name}\n")
                if game.has_game_banner:
                    f.write(f"https://smashcustommusic.net/logos/{game.id}.png\n" +
                    f"  dir={download_path / str(game.id)}\n" +
                     "  out=banner.png\n\n"
                    )
                    bar()
                for i, song in enumerate(game.songs):
                    # song_urls.append(f"https://smashcustommusic.net/brstm/{song.id}?noIncrement=1")
                    bar.text = f"-> [{game.id}] ({i+1}/{len(game.songs)}) \"{game.name}\""
                    f.write(f"https://smashcustommusic.net/brstm/{song.id}?noIncrement=1\n" +
                    f"  dir={download_path / str(game.id) / str(song.id)}\n" +
                    (f"  out={song.name}.brstm\n\n" if auto_filename_aria2 else "\n")
                    )
                    if use_aria2_asap:
                        f.write(f"https://smashcustommusic.net/json/song/{song.id}\n" +
                            f"  dir={download_path / str(game.id) / str(song.id)}\n" +
                             "  out=data.json\n\n"
                        )
                    bar()
