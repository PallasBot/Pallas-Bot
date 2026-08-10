"""Bot git 管理：状态、历史与定向 checkout/reset。"""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Callable
from typing import Any

import httpx
from nonebot import logger

from packages.pb_webui.manager import (
    BotGitUpdateError,
    bot_branch_update_probe,
    fetch_bot_origin_refs,
    fetch_latest_bot_release,
    get_bot_current_version,
    inspect_bot_deployment,
    is_bot_release_style_tag,
    normalize_bot_update_track,
    resolve_bot_upstream_ref,
)
from pallas.core.foundation.bot_version import pallas_bot_repo_root
from pallas.core.shared.utils.format_exception import format_exception_for_log
from pallas.core.shared.utils.git_mirror import (
    MirrorSpec,
    git_instead_of_args,
    iter_mirrors_for_failover,
)
from pallas.core.shared.utils.github_release import fetch_github_releases

ProgressReporter = Callable[[int, str], None]

_GIT_LOG_COMMIT_FORMAT = "%H|%ai|%s"
_GIT_TAG_LIST_FORMAT = "%(refname:short)|%(creatordate:iso)|%(subject)"
# 控制台分支轨道仅允许官方主干，避免误切到 feature / 本地克隆分支
BOT_GIT_TRACK_BRANCHES: tuple[str, ...] = ("dev", "main")


def bot_repo_root():
    return pallas_bot_repo_root()


def normalize_bot_git_track_branch(value: object, *, default: str = "dev") -> str:
    """将分支名规范为允许列表中的一项；空/非法时回落 default。"""
    name = str(value or "").strip().removeprefix("origin/")
    if name in BOT_GIT_TRACK_BRANCHES:
        return name
    fallback = str(default or "dev").strip()
    return fallback if fallback in BOT_GIT_TRACK_BRANCHES else "dev"


def require_bot_git_track_branch(value: object) -> str:
    """apply 路径：显式非法分支名直接拒绝（空串可回落为 dev）。"""
    name = str(value or "").strip().removeprefix("origin/")
    if not name:
        return "dev"
    if name in BOT_GIT_TRACK_BRANCHES:
        return name
    allowed = " / ".join(BOT_GIT_TRACK_BRANCHES)
    raise BotGitUpdateError(
        f"分支轨道仅允许跟踪 {allowed}，收到：{name}",
        status_code=400,
    )


def list_bot_track_branches() -> list[str]:
    """控制台可选跟踪分支（固定 allowlist）。"""
    return list(BOT_GIT_TRACK_BRANCHES)


def git_rev_parse_text(*args: str, timeout_s: float = 8.0) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", *args],
            cwd=bot_repo_root(),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout_s,
        ).strip()
    except Exception:  # noqa: BLE001
        return None


def normalize_git_history_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    return "release" if mode == "release" else "commit"


def normalize_git_apply_mode(value: object) -> str:
    return normalize_git_history_mode(value)


def normalize_git_apply_strategy(value: object) -> str:
    strategy = str(value or "").strip().lower()
    return "force" if strategy == "force" else "safe"


def list_bot_remote_branches() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
            cwd=bot_repo_root(),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8.0,
        )
    except Exception:  # noqa: BLE001
        return []
    names: list[str] = []
    for line in out.splitlines():
        short = line.strip().removeprefix("origin/")
        if not short or short == "HEAD":
            continue
        names.append(short)
    return sorted(set(names))


def get_bot_head_info() -> dict[str, str] | None:
    sha = git_rev_parse_text("HEAD")
    if not sha:
        return None
    short_sha = git_rev_parse_text("--short=7", "HEAD") or (sha[:7] if len(sha) >= 7 else sha)
    tag = ""
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=bot_repo_root(),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8.0,
        ).strip()
    except Exception:  # noqa: BLE001
        tag = ""
    date = ""
    message = ""
    try:
        log_line = subprocess.check_output(
            ["git", "log", "-1", "--format=%ai|%s", "HEAD"],
            cwd=bot_repo_root(),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8.0,
        ).strip()
        if "|" in log_line:
            date, message = log_line.split("|", 1)
    except Exception:  # noqa: BLE001
        pass
    return {
        "sha": sha,
        "short_sha": short_sha,
        "tag": tag,
        "date": date.strip(),
        "message": message.strip(),
    }


def parse_commit_history_line(line: str) -> dict[str, str] | None:
    raw = (line or "").strip()
    if not raw:
        return None
    parts = raw.split("|", 2)
    if len(parts) != 3:
        return None
    sha, date, message = (p.strip() for p in parts)
    if not sha:
        return None
    short_ref = sha[:7] if len(sha) >= 7 else sha
    return {
        "kind": "commit",
        "ref": sha,
        "short_ref": short_ref,
        "date": date,
        "message": message,
    }


def parse_release_history_line(line: str) -> dict[str, str] | None:
    raw = (line or "").strip()
    if not raw:
        return None
    parts = raw.split("|", 2)
    if len(parts) != 3:
        return None
    ref, date, message = (p.strip() for p in parts)
    if not ref or not is_bot_release_style_tag(ref):
        return None
    return {
        "kind": "release",
        "ref": ref,
        "short_ref": ref,
        "date": date,
        "message": message,
    }


def history_item_is_head(item: dict[str, str], *, head_sha: str, head_tag: str) -> bool:
    ref = str(item.get("ref") or "").strip()
    if not ref:
        return False
    if head_tag and ref == head_tag:
        return True
    if not head_sha:
        return False
    if ref == head_sha:
        return True
    if head_sha.startswith(ref) and len(ref) >= 4:
        return True
    if len(ref) >= 7 and head_sha.startswith(ref):
        return True
    if len(head_sha) >= 7 and ref.startswith(head_sha[:12]):
        return True
    return False


def mark_history_items(
    items: list[dict[str, str]],
    *,
    head_sha: str = "",
    head_tag: str = "",
) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        row = dict(item)
        row["is_head"] = history_item_is_head(item, head_sha=head_sha, head_tag=head_tag)
        row["is_latest"] = i == 0
        marked.append(row)
    return marked


def git_run_sync(*args: str, timeout_s: float = 8.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=bot_repo_root(),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    return int(proc.returncode or 0), out, err


def load_commit_history(*, branch: str, limit: int = 30) -> list[dict[str, str]]:
    branch_name = (branch or "").strip().removeprefix("origin/")
    if not branch_name:
        upstream = resolve_bot_upstream_ref()
        branch_name = upstream.removeprefix("origin/") if upstream else ""
    if not branch_name:
        return []
    ref = f"origin/{branch_name}"
    rc, out, _ = git_run_sync(
        "log",
        ref,
        f"-{max(1, min(limit, 100))}",
        f"--format={_GIT_LOG_COMMIT_FORMAT}",
        timeout_s=15.0,
    )
    if rc != 0:
        return []
    items: list[dict[str, str]] = []
    for line in out.splitlines():
        parsed = parse_commit_history_line(line)
        if parsed is not None:
            items.append(parsed)
    return items


def load_release_history(*, limit: int = 30) -> list[dict[str, str]]:
    rc, out, _ = git_run_sync(
        "for-each-ref",
        "--sort=-creatordate",
        f"--format={_GIT_TAG_LIST_FORMAT}",
        "refs/tags",
        timeout_s=15.0,
    )
    if rc != 0:
        return []
    items: list[dict[str, str]] = []
    for line in out.splitlines():
        parsed = parse_release_history_line(line)
        if parsed is not None:
            items.append(parsed)
        if len(items) >= max(1, min(limit, 100)):
            break
    return items


async def build_bot_git_status_payload(
    *,
    update_track: str,
    update_branch: str,
    fetch: bool = True,
    restart_available: bool = False,
) -> dict[str, Any]:
    track = normalize_bot_update_track(update_track)
    preferred_branch = normalize_bot_git_track_branch(update_branch)
    deploy = inspect_bot_deployment()
    git_available = bool(deploy.get("git_available"))
    head = get_bot_head_info() if git_available else None
    branches = list_bot_track_branches()

    upstream_ref = ""
    latest_commit = ""
    commits_behind = 0

    if git_available and track == "branch":
        if fetch:
            try:
                await fetch_bot_origin_refs()
            except BotGitUpdateError as e:
                logger.warning("Pallas-Bot 控制台: Bot git status fetch 失败 err={}", e.detail)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Pallas-Bot 控制台: Bot git status fetch 异常 err={}",
                    format_exception_for_log(e),
                )
        probe = bot_branch_update_probe(preferred_branch=preferred_branch)
        upstream_ref = str(probe.get("upstream_ref") or "")
        latest_commit = str(probe.get("latest_commit") or "")
        commits_behind = int(probe.get("commits_behind") or 0)

    return {
        "update_track": track,
        "update_branch": preferred_branch,
        "branches": branches,
        "head": head,
        "upstream_ref": upstream_ref,
        "latest_commit": latest_commit,
        "commits_behind": commits_behind,
        **deploy,
        "restart_available": restart_available,
        "git_available": git_available,
    }


async def load_bot_git_history_payload(
    *,
    mode: str,
    branch: str = "",
    limit: int = 30,
    fetch: bool = True,
    github_token: str = "",
    repo: str = "PallasBot/Pallas-Bot",
) -> dict[str, Any]:
    history_mode = normalize_git_history_mode(mode)
    preferred_branch = normalize_bot_git_track_branch(branch) if history_mode == "commit" else ""
    deploy = inspect_bot_deployment()
    git_available = bool(deploy.get("git_available"))
    head = get_bot_head_info() if git_available else None
    head_sha = str((head or {}).get("sha") or "")
    head_tag = str((head or {}).get("tag") or "")

    if git_available and fetch:
        try:
            await fetch_bot_origin_refs()
        except BotGitUpdateError as e:
            logger.warning("Pallas-Bot 控制台: Bot git history fetch 失败 err={}", e.detail)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Pallas-Bot 控制台: Bot git history fetch 异常 err={}",
                format_exception_for_log(e),
            )

    if not git_available and history_mode == "release" and deploy.get("deployment_mode") == "docker":
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            releases = await fetch_github_releases(
                repo,
                client=client,
                limit=max(1, min(limit, 100)),
                token=github_token,
            )
        runtime_tag = str(deploy.get("runtime_version") or deploy.get("image_version") or "")
        raw_items = [
            {
                "kind": "release",
                "ref": str(release.get("tag") or ""),
                "short_ref": str(release.get("tag") or ""),
                "date": str(release.get("published_at") or ""),
                "message": str(release.get("name") or release.get("tag") or ""),
            }
            for release in releases
            if is_bot_release_style_tag(str(release.get("tag") or ""))
        ]
        return {
            "mode": history_mode,
            "branch": "",
            "items": mark_history_items(raw_items, head_tag=runtime_tag),
            "head": {"tag": runtime_tag, "sha": "", "short_sha": ""} if runtime_tag else None,
        }

    if not git_available:
        return {
            "mode": history_mode,
            "branch": preferred_branch,
            "items": [],
            "head": None,
        }

    if history_mode == "release":
        raw_items = load_release_history(limit=limit)
    else:
        raw_items = load_commit_history(branch=preferred_branch, limit=limit)

    items = mark_history_items(raw_items, head_sha=head_sha, head_tag=head_tag)
    return {
        "mode": history_mode,
        "branch": preferred_branch,
        "items": items,
        "head": head,
    }


async def apply_bot_git_target(
    *,
    github_token: str = "",
    repo: str = "PallasBot/Pallas-Bot",
    mode: str = "release",
    preferred_branch: str = "",
    target_ref: str = "",
    strategy: str = "safe",
    on_progress: ProgressReporter | None = None,
) -> dict[str, str]:
    """定向更新 Bot 仓库：release tag 或 commit/分支 tip。"""
    root = bot_repo_root()
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    apply_mode = normalize_git_apply_mode(mode)
    apply_strategy = normalize_git_apply_strategy(strategy)
    ref_input = (target_ref or "").strip()
    branch_pref = ""
    if apply_mode == "commit":
        branch_pref = require_bot_git_track_branch(preferred_branch)
    else:
        branch_pref = str(preferred_branch or "").strip().removeprefix("origin/")
        if branch_pref and branch_pref not in BOT_GIT_TRACK_BRANCHES:
            branch_pref = ""

    def report(pct: int, message: str) -> None:
        if on_progress is not None:
            on_progress(pct, message)

    async def git(
        *args: str,
        cmd_timeout_s: float = 180.0,
        mirror: MirrorSpec | None = None,
    ) -> tuple[int, str, str]:
        prefix = git_instead_of_args(mirror) if mirror is not None else []
        proc = await asyncio.create_subprocess_exec(
            "git",
            *prefix,
            *args,
            cwd=str(root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=cmd_timeout_s)
        except asyncio.TimeoutError:  # noqa: UP041
            proc.kill()
            await proc.wait()
            msg = "git 操作超时，请检查网络或稍后在命令行重试"
            raise BotGitUpdateError(msg, status_code=504) from None
        out = out_b.decode(errors="replace").strip() if out_b else ""
        err = err_b.decode(errors="replace").strip() if err_b else ""
        return int(proc.returncode or 0), out, err

    async def git_remote(*args: str, cmd_timeout_s: float = 180.0) -> tuple[int, str, str]:
        last_code = 1
        last_out = ""
        last_err = ""
        mirrors = list(iter_mirrors_for_failover("bot"))
        for i, mirror in enumerate(mirrors, start=1):
            logger.info(
                "Pallas-Bot 控制台: Bot git {} 尝试 {}/{} mirror={}",
                " ".join(args[:3]),
                i,
                len(mirrors),
                mirror.id,
            )
            code, out, err = await git(*args, cmd_timeout_s=cmd_timeout_s, mirror=mirror)
            if code == 0:
                return code, out, err
            last_code, last_out, last_err = code, out, err
            logger.warning(
                "Pallas-Bot 控制台: Bot git mirror={} 失败：{}",
                mirror.id,
                (err or out or f"exit={code}")[:300],
            )
        return last_code, last_out, last_err

    async def resolve_commitish(ref: str) -> str:
        candidate = (ref or "").strip()
        if not candidate:
            raise BotGitUpdateError("未指定目标 ref", status_code=400)
        for probe in (candidate, f"{candidate}^{{commit}}", f"refs/tags/{candidate}"):
            rc, out, _ = await git("rev-parse", "-q", "--verify", probe)
            if rc == 0 and out:
                return out.strip()
        raise BotGitUpdateError(f"无法解析目标 ref：{candidate}", status_code=400)

    report(4, "检查 git 工作副本…")
    rc, out, _ = await git("rev-parse", "--is-inside-work-tree")
    if rc != 0 or out != "true":
        raise BotGitUpdateError(
            "当前运行目录不是 git 工作副本（例如 Docker 仅含镜像内文件）。请使用 docker compose pull "
            "或按文档手动部署更新。",
            status_code=400,
        )

    report(18, "git fetch origin…")
    rc, _, fetch_err = await git_remote("fetch", "origin", "--tags", cmd_timeout_s=300.0)
    if rc != 0:
        raise BotGitUpdateError(f"git fetch 失败：{fetch_err or '(无 stderr)'}", status_code=502)

    release_tag = ""
    if apply_mode == "release":
        if ref_input:
            if not is_bot_release_style_tag(ref_input):
                raise BotGitUpdateError(f"目标标签 {ref_input} 不是 release 风格（vX.Y.Z）", status_code=400)
            release_tag = ref_input
        else:
            report(24, "获取最新发布信息…")
            try:
                latest = await fetch_latest_bot_release(repo, token=github_token)
            except Exception as e:  # noqa: BLE001
                raise BotGitUpdateError(
                    f"无法从 GitHub 获取最新发布信息：{format_exception_for_log(e)}",
                    status_code=502,
                ) from e
            release_tag = str(latest.get("tag", "") or "").strip()
            if not release_tag:
                raise BotGitUpdateError("GitHub 未返回可用的发布标签。", status_code=502)

    upstream = resolve_bot_upstream_ref(preferred_branch=branch_pref)
    branch_name = branch_pref or (upstream.removeprefix("origin/") if upstream else "")

    target_sha = ""
    if apply_mode == "commit":
        if ref_input:
            target_sha = await resolve_commitish(ref_input)
        elif upstream:
            rc_up, remote_sha, _ = await git("rev-parse", upstream)
            if rc_up != 0 or not remote_sha:
                raise BotGitUpdateError(f"无法解析 {upstream}", status_code=400)
            target_sha = remote_sha.strip()
            branch_name = upstream.removeprefix("origin/")
        else:
            raise BotGitUpdateError(
                "无法解析跟踪分支。请指定 branch 或配置 pallas_bot_update_branch。",
                status_code=400,
            )
    elif apply_strategy == "force":
        target_sha = await resolve_commitish(release_tag)

    if apply_strategy == "force":
        hard_ref = target_sha or await resolve_commitish(release_tag)
        report(60, f"强制重置至 {hard_ref[:12]}…")
        rc_reset, _, err_reset = await git("reset", "--hard", hard_ref)
        if rc_reset != 0:
            raise BotGitUpdateError(
                f"git reset --hard 失败：{err_reset or '(无 stderr)'}",
                status_code=400,
            )
        logger.info("Pallas-Bot 控制台: Bot 已 force reset 至 {}", hard_ref[:12])
        report(92, "整理版本信息…")
        after = get_bot_current_version()
        display = str(after.get("tag") or after.get("commit") or hard_ref[:12]).strip()
        report(98, f"仓库已更新至 {display}")
        return {
            "tag": display,
            "message": f"仓库已强制重置至 {display}。请重启 Bot 进程后加载新代码。",
        }

    if apply_mode == "commit":
        if not branch_name:
            raise BotGitUpdateError("commit 模式需要可解析的分支名", status_code=400)
        upstream_ref = f"origin/{branch_name}"
        rc_verify, _, _ = await git("rev-parse", "-q", "--verify", upstream_ref)
        if rc_verify != 0:
            raise BotGitUpdateError(f"远端不存在分支 {upstream_ref}", status_code=400)

        current = get_bot_current_version()
        current_commit_full = git_rev_parse_text("HEAD") or ""
        if target_sha and current_commit_full == target_sha:
            display = str(current.get("tag") or current.get("commit") or target_sha[:12]).strip()
            report(100, f"已处于目标提交 {display}")
            return {
                "tag": display,
                "message": f"已处于目标提交 {display}，无需更新。",
            }

        rc_br, cur_branch, _ = await git("rev-parse", "--abbrev-ref", "HEAD")
        rc_dirty, porcelain, _ = await git("status", "--porcelain")
        dirty = bool(porcelain.strip())
        stashed = False
        if dirty:
            report(36, "暂存本地改动…")
            stash_target = target_sha[:12] if target_sha else branch_name
            rc_st, _, err_st = await git(
                "stash",
                "push",
                "-u",
                "-m",
                f"pallas-webui: auto stash before bot commit update to {stash_target}",
            )
            if rc_st != 0:
                raise BotGitUpdateError(
                    f"自动暂存本地改动失败：{err_st or '(无 stderr)'}",
                    status_code=409,
                )
            stashed = True

        report(45, f"切换到分支 {branch_name}…")
        if rc_br != 0 or cur_branch != branch_name:
            rc_co, _, err_co = await git("checkout", "-B", branch_name, upstream_ref)
            if rc_co != 0:
                if stashed:
                    await git("stash", "pop")
                raise BotGitUpdateError(
                    f"切换到分支 {branch_name} 失败：{err_co or '(无 stderr)'}",
                    status_code=400,
                )

        if ref_input:
            report(58, f"快进合并至 {target_sha[:12]}…")
            rc_m, _, err_m = await git("merge", "--ff-only", target_sha)
            if rc_m != 0:
                if stashed:
                    await git("stash", "pop")
                raise BotGitUpdateError(
                    f"git merge --ff-only {target_sha[:12]} 失败：{err_m or '(无 stderr)'}",
                    status_code=400,
                )
        else:
            probe = bot_branch_update_probe(preferred_branch=branch_pref)
            if not probe.get("has_update") and not probe.get("error"):
                after = get_bot_current_version()
                display = str(after.get("tag") or after.get("commit") or branch_name).strip()
                report(100, f"已与 {upstream_ref} 同步")
                if stashed:
                    await git("stash", "pop")
                return {
                    "tag": display,
                    "message": f"已与 {upstream_ref} 同步（{display}），无需更新。",
                }
            report(58, f"拉取 {upstream_ref}…")
            rc_p, _, err_p = await git_remote("pull", "--ff-only", "--autostash", "origin", branch_name)
            if rc_p != 0:
                if stashed:
                    await git("stash", "pop")
                raise BotGitUpdateError(
                    f"git pull --ff-only origin {branch_name} 失败：{err_p or '(无 stderr)'}",
                    status_code=400,
                )

        stash_note = ""
        if stashed:
            report(78, "恢复本地改动…")
            rc_sp, _, err_sp = await git("stash", "pop")
            if rc_sp != 0:
                stash_note = " 本地改动已暂存但未自动恢复，请手动 git stash pop。"
                logger.warning("Pallas-Bot 控制台: commit 更新后 stash pop 失败 err={}", err_sp)
            else:
                stash_note = " 已自动恢复先前暂存的本地改动。"

        report(92, "整理版本信息…")
        after = get_bot_current_version()
        display = str(after.get("tag") or after.get("commit") or branch_name).strip()
        report(98, f"仓库已更新至 {display}")
        return {
            "tag": display,
            "message": f"仓库已更新至 {upstream_ref}（{display}）。请重启 Bot 进程后加载新代码。{stash_note}",
        }

    # release + safe
    tag_peel = f"{release_tag}^{{}}"
    rc_peel, _, _ = await git("rev-parse", "-q", "--verify", tag_peel)
    rc_tag, _, _ = await git("rev-parse", "-q", "--verify", f"refs/tags/{release_tag}")
    if rc_peel != 0 and rc_tag != 0:
        raise BotGitUpdateError(
            f"fetch 后仍无法解析标签 {release_tag}，请确认远端存在该发布。",
            status_code=400,
        )
    detach_ref = tag_peel if rc_peel == 0 else f"refs/tags/{release_tag}"

    current = get_bot_current_version()
    current_tag = str(current.get("tag", "") or "").strip()
    if current_tag and current_tag == release_tag:
        commit = str(current.get("commit", "") or "").strip()
        report(100, f"已处于发布标签 {release_tag}")
        return {
            "tag": release_tag,
            "message": f"已处于发布标签 {release_tag}（{commit or 'commit 未知'}），无需更新。",
        }

    rc, porcelain, _ = await git("status", "--porcelain")
    dirty = bool(porcelain.strip())
    stashed = False
    stash_restore_note = ""

    if current_tag or ref_input:
        if dirty:
            report(40, "暂存本地改动…")
            rc_st, _, err_st = await git(
                "stash",
                "push",
                "-u",
                "-m",
                f"pallas-webui: auto stash before bot update to {release_tag}",
            )
            if rc_st != 0:
                raise BotGitUpdateError(
                    f"自动暂存本地改动失败：{err_st or '(无 stderr)'}",
                    status_code=409,
                )
            stashed = True
        report(55, f"切换到标签 {release_tag}…")
        rc_co, _, err_co = await git("checkout", "--detach", detach_ref)
        if rc_co != 0:
            if stashed:
                await git("stash", "pop")
            raise BotGitUpdateError(
                f"切换到标签 {release_tag} 失败：{err_co or '(无 stderr)'}",
                status_code=400,
            )
        if stashed:
            report(78, "恢复本地改动…")
            rc_sp, _, err_sp = await git("stash", "pop")
            if rc_sp != 0:
                stash_restore_note = " 本地改动已暂存但未自动恢复，请手动 git stash pop。"
                logger.warning("Pallas-Bot 控制台: release 更新后 stash pop 失败 err={}", err_sp)
            else:
                stash_restore_note = " 已自动恢复先前暂存的本地改动。"
    else:
        report(45, "拉取最新提交…")
        rc_u, upstream_out, _ = await git("rev-parse", "--abbrev-ref", "@{u}")
        if rc_u == 0 and upstream_out:
            rc_p, _, err_p = await git_remote("pull", "--ff-only", "--autostash")
            if rc_p != 0:
                raise BotGitUpdateError(
                    f"git pull --ff-only 失败（已配置上游 {upstream_out}）：{err_p or '(无 stderr)'}",
                    status_code=400,
                )
        else:
            def_branch = branch_name or "master"
            if not branch_name:
                rc_sym, sym_out, _ = await git("symbolic-ref", "-q", "refs/remotes/origin/HEAD")
                if rc_sym == 0 and sym_out.startswith("refs/remotes/origin/"):
                    def_branch = sym_out.rsplit("/", maxsplit=1)[-1]
                else:
                    for cand in ("master", "main"):
                        rc_ob, _, _ = await git("rev-parse", "-q", "--verify", f"origin/{cand}")
                        if rc_ob == 0:
                            def_branch = cand
                            break
            rc_p, _, err_p = await git_remote("pull", "--ff-only", "--autostash", "origin", def_branch)
            if rc_p != 0:
                raise BotGitUpdateError(
                    f"git pull --ff-only --autostash origin {def_branch} 失败：{err_p or '(无 stderr)'}",
                    status_code=400,
                )

    report(92, "整理版本信息…")
    after = get_bot_current_version()
    display = str(after.get("tag") or after.get("commit") or release_tag).strip()
    report(98, f"仓库已更新至 {display}")
    return {
        "tag": display,
        "message": f"仓库已更新（{display}）。请重启 Bot 进程后加载新代码。{stash_restore_note}",
    }
