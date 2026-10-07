"""PhotoCraft アダプタ層。

本家の仕様に依存する知識（asset 名と展開後のパス、CLI 引数、アクションリスト形式、
batch の出力形式、入力として読める拡張子、params 書式）はこのモジュールだけに置く
（requirements.md §4 耐変更性）。根拠は requirements.md §9 と docs/upstream-snapshot/<tag>/。
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

UPSTREAM = "storytold/photocraft"
RELEASES_API = f"https://api.github.com/repos/{UPSTREAM}/releases"
RELEASE_DOWNLOAD = f"https://github.com/{UPSTREAM}/releases/download"
GIT_URL = f"https://github.com/{UPSTREAM}"
CHECKSUMS = "SHA256SUMS.txt"

# batch が入力として拾う拡張子（apps/photocraft-cli/src/lib.rs の is_input と
# crates/codecs/src/format.rs。AVIF は書き出し専用で読めない）。v0.2.0 で確認。
INPUT_EXTENSIONS = frozenset(
    {
        "pcraft", "psd", "psb",
        "png", "apng", "jpg", "jpeg", "jpe", "jfif", "tif", "tiff", "webp", "gif",
        "bmp", "dib", "tga", "icb", "vda", "vst", "ico",
        "pnm", "pbm", "pgm", "ppm", "pam", "pfm", "qoi", "exr", "hdr",
    }
)

# --format に渡せる主な書き出し形式（拡張子）。空文字は「入力と同じ」。
OUTPUT_FORMATS = ("", "png", "jpg", "tif", "webp", "psd", "pcraft", "gif", "bmp", "tga", "qoi", "exr")


class UnsupportedPlatform(RuntimeError):
    pass


@dataclass(frozen=True)
class Asset:
    """リリース asset 1件と、その中の photocraft-cli の位置。"""

    name: str  # asset のファイル名
    cli_relpath: str  # 展開先からの CLI の相対パス（/ 区切り）
    archive: str  # "tar.gz" または "zip"


def _version(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def version_tuple(tag: str) -> tuple[int, int, int] | None:
    """`v0.3.0` や `v0.3.0-rc.1` の数字部分。解釈できなければ None（プレリリースの接尾辞は無視する）。"""
    m = _SEMVER.match(tag)
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def at_least(tag: str, major: int, minor: int, patch: int) -> bool:
    v = version_tuple(tag)
    return v is not None and v >= (major, minor, patch)


def asset_candidates(tag: str, system: str | None = None, machine: str | None = None) -> list[Asset]:
    """実行中の OS 向けの asset を、使いたい順に返す（requirements.md FR-02 の表）。

    Windows ARM64 は、v0.3.0 からネイティブ版（`windows-arm64-portable.zip`）がある。それより前の版は
    ARM64 版がないので、Windows 11 の x64 エミュレーションで x64 版を使う。
    """
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    ver = _version(tag)
    if system == "linux":
        arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine)
        if arch is None:
            raise UnsupportedPlatform(f"Linux {machine} 向けのリリースはありません")
        base = f"photocraft-{ver}-linux-{arch}"
        return [Asset(f"{base}.tar.gz", f"{base}/bin/photocraft-cli", "tar.gz")]
    if system == "darwin":
        base = f"photocraft-cli-{ver}-macos-universal"
        return [Asset(f"{base}.zip", f"{base}/photocraft-cli", "zip")]
    if system == "windows":
        arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "x86": "x86", "i386": "x86", "i686": "x86"}.get(machine)
        if arch is None:
            raise UnsupportedPlatform(f"Windows {machine} 向けのリリースはありません")
        archs = ["arm64", "x64"] if arch == "arm64" and at_least(tag, 0, 3, 0) else ["x64"] if arch == "arm64" else [arch]
        return [Asset(f"photocraft-{ver}-windows-{a}-portable.zip", f"photocraft-{ver}-windows-{a}-portable/photocraft-cli.exe", "zip") for a in archs]
    raise UnsupportedPlatform(f"{system} 向けのリリースはありません")


def asset_for(tag: str, system: str | None = None, machine: str | None = None) -> Asset:
    """実行中の OS 向けの、最優先の asset。"""
    return asset_candidates(tag, system, machine)[0]


def asset_url(tag: str, name: str) -> str:
    return f"{RELEASE_DOWNLOAD}/{tag}/{name}"


def checksum_for(sums_text: str, name: str) -> str | None:
    """SHA256SUMS.txt（`<hash>  <name>` 形式）から name の hash を返す。"""
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    return None


# ---- CLI 引数 -----------------------------------------------------------------


def version_args(cli: Path) -> list[str]:
    return [str(cli), "--version"]


def commands_args(cli: Path) -> list[str]:
    return [str(cli), "commands", "--json"]


def batch_args(cli: Path, actions: Path, in_dir: Path, out_dir: Path, fmt: str = "", quality: int | None = None) -> list[str]:
    args = [str(cli), "batch", "--actions", str(actions), "--in", str(in_dir), "--out", str(out_dir)]
    if fmt:
        args += ["--format", fmt]
    if quality is not None:
        args += ["--quality", str(quality)]
    return args


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def cli_version(cli: Path, timeout: float = 30) -> str:
    """`photocraft-cli --version` の出力（例: `photocraft-cli 0.2.0 (ad8632173, 2026-10-05)`）。"""
    r = subprocess.run(
        version_args(cli), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_no_window(),
    )
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(version_args(cli))} が終了コード {r.returncode} で失敗: {r.stderr.strip()}")
    return r.stdout.strip()


@dataclass(frozen=True)
class Command:
    id: str
    label: str
    menu: str
    params_doc: str


def parse_registry(text: str) -> dict[str, Command]:
    """`commands --json` の出力をコマンド ID で引ける形にする。"""
    out: dict[str, Command] = {}
    for c in json.loads(text):
        cid = c.get("id")
        if not isinstance(cid, str):
            continue
        menu = c.get("menu") or []
        out[cid] = Command(cid, c.get("label") or "", " > ".join(m for m in menu if isinstance(m, str)), c.get("params") or "")
    return out


def load_registry(cli: Path, timeout: float = 60) -> dict[str, Command]:
    r = subprocess.run(
        commands_args(cli), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_no_window(),
    )
    if r.returncode != 0:
        raise RuntimeError(f"commands --json が終了コード {r.returncode} で失敗: {r.stderr.strip()}")
    return parse_registry(r.stdout)


def param_keys(params_doc: str) -> set[str] | None:
    """params 書式文字列（例: `{"amount":1..500=100,"radius":…}`）に出てくるキー名。

    書式は自由形式の文字列なので、`"key":` の形をすべて拾う（入れ子のキーも含むため、
    未知キーの警告は取りこぼし寄り）。書式が空なら None（照合しない）。
    """
    if not params_doc:
        return None
    return set(re.findall(r'"(\w+)"\s*:', params_doc))


def supports_automation_roots(tag: str) -> bool:
    """`mcp` / `serve` の --automation-read-root / --automation-write-root が効く版か。

    v0.2.0 で追加（v0.1.1 はオプションを黙って無視し、絶対パスも通る。mcp/README.md）。
    v0.2.0 より前の版は「効かない」、以降は「効く」とみなす。
    """
    return at_least(tag, 0, 2, 0)


def batch_collision(tag: str) -> str:
    """同じ名前の出力が1回の実行で重なったときの挙動。

    "overwrite": 後の画像が先の結果を黙って上書きする（v0.2.0 まで。3 件とも成功と数える）。
    "fail": 後の画像は書かずに失敗にする。先の結果は残る（v0.3.0 から。`already holds the result of … from this run`）。
    実機で確認（2026-10-07）。出力フォルダに前から在るファイルは、どちらの版でも上書きされる。
    """
    return "fail" if at_least(tag, 0, 3, 0) else "overwrite"


# ---- アクションリスト ----------------------------------------------------------


@dataclass(frozen=True)
class Step:
    index: int
    command: str
    params: dict


@dataclass(frozen=True)
class Parsed:
    steps: list[Step]
    errors: list[str]
    newer: list[str]  # v0.3.0 以降でしか読めない書き方（v0.2.0 以前ではエラーになる）


def parse_actions_ex(data: object) -> Parsed:
    """CLI の `batch --actions` と同じ解釈でステップを取り出す。エラーは集めて返す。

    v0.2.0 まで: `[{"command": id, "params": {…}}, …]` または `{"actions": [...]}`。`"id"` は `"command"` の別名。
    v0.3.0 から（crates/engine/src/automate_cmds.rs の parse_action / parse_steps）:
      - ステップは `{"command"|"id", "params"?}` のほか、`[id, params?]` と `"id"` だけでも書ける
      - 最上位は配列、`{"steps": [...]}`、`{"action": {"steps": [...]}}`（`action` が配列でもよい）、
        `{"actions": …}`（値が配列、または上の形のオブジェクト）
    `params` は省略可（`{}`）。他のキーは CLI が無視する。後者を使うと `newer` に理由が入る。
    """
    newer: list[str] = []

    def note(why: str) -> None:
        if why not in newer:
            newer.append(why)

    if isinstance(data, dict) and "actions" in data:
        data, wrapped = data["actions"], True
    else:
        wrapped = False
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if wrapped:
            note('"actions" にオブジェクトを書く形式')
        if "steps" in data:
            items = data["steps"]
            note('{"steps": […]} 形式')
        elif "action" in data:
            inner = data["action"]
            items = inner["steps"] if isinstance(inner, dict) and "steps" in inner else inner
            note('{"action": …} 形式')
        else:
            return Parsed([], ['オブジェクト形式には配列の "actions"（または "steps"）が必要です'], newer)
        if not isinstance(items, list):
            return Parsed([], ["ステップは配列にしてください"], newer)
    elif wrapped:
        return Parsed([], ['"actions" は配列にしてください'], newer)
    else:
        return Parsed([], ["最上位は配列、または {\"actions\": [...]} のオブジェクトにしてください"], newer)

    steps: list[Step] = []
    errors: list[str] = []
    for i, item in enumerate(items):
        n = i + 1
        if isinstance(item, dict):
            cmd = item.get("command", item.get("id"))
            params = item.get("params", {})
            if not isinstance(cmd, str) or not cmd:
                errors.append(f'ステップ {n}: "command" がありません')
                continue
        elif isinstance(item, list) and item:
            note("ステップを [ID, params] の配列で書く形式")
            cmd, params = item[0], item[1] if len(item) > 1 else {}
            if not isinstance(cmd, str) or not cmd:
                errors.append(f"ステップ {n}: 配列の先頭（コマンド ID）は文字列にしてください")
                continue
        elif isinstance(item, str):
            note("ステップを ID の文字列だけで書く形式")
            cmd, params = item, {}
            if not cmd:
                errors.append(f"ステップ {n}: コマンド ID が空です")
                continue
        else:
            errors.append(f'ステップ {n}: {{"command": …}}・[ID, params]・ID のどれかで書いてください')
            continue
        if params is None:
            params = {}
        if not isinstance(params, dict):
            errors.append(f'ステップ {n}（{cmd}）: "params" はオブジェクトにしてください')
            continue
        steps.append(Step(i, cmd, params))
    if not items:
        errors.append("ステップが1つもありません")
    return Parsed(steps, errors, newer)


def parse_actions(data: object) -> tuple[list[Step], list[str]]:
    """`parse_actions_ex` のステップとエラーだけ。"""
    r = parse_actions_ex(data)
    return r.steps, r.errors


# ---- batch -------------------------------------------------------------------


def list_inputs(in_dir: Path) -> list[Path]:
    """batch が処理する入力（フォルダ直下のみ、再帰なし、名前順）。"""
    if not in_dir.is_dir():
        return []
    return sorted(p for p in in_dir.iterdir() if p.is_file() and p.suffix[1:].lower() in INPUT_EXTENSIONS)


def output_name(input_path: Path, fmt: str = "") -> str:
    """batch の出力ファイル名 `<stem>.<ext>`（ext は --format、なければ入力の拡張子）。"""
    ext = fmt or input_path.suffix[1:] or "png"
    return f"{input_path.stem}.{ext}"


_OK = re.compile(r"^ok\s+(.*) -> (.*)$")
_FAIL = re.compile(r"^FAIL\s+(.*?): (.*)$")
_SUMMARY = re.compile(r"^(\d+) succeeded, (\d+) failed$")


@dataclass(frozen=True)
class BatchLine:
    kind: str  # "ok" / "fail" / "summary" / "warning" / "error" / "other"
    a: str = ""  # ok: 入力 / fail: 入力 / summary: 成功数 / warning・error: 本文
    b: str = ""  # ok: 出力 / fail: 理由 / summary: 失敗数


def parse_batch_line(line: str) -> BatchLine:
    """batch の1行を分類する。stdout は ok と集計、stderr は FAIL・warning・error。"""
    line = line.rstrip("\r\n")
    if m := _OK.match(line):
        return BatchLine("ok", m[1], m[2])
    if m := _FAIL.match(line):
        return BatchLine("fail", m[1], m[2])
    if m := _SUMMARY.match(line):
        return BatchLine("summary", m[1], m[2])
    if line.startswith("warning: "):
        return BatchLine("warning", line[len("warning: "):])
    if line.startswith("error: "):
        return BatchLine("error", line[len("error: "):])
    return BatchLine("other", line)
