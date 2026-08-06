#!/usr/bin/env python3
"""brain CLI 어댑터 3종 — ingest / evaluate / publish.

판정 규칙(D1~D6·R1~R6)은 brain 코드가 소유한다 — 여기서는 argv 만 만든다(§3).
measure/audit 접합은 Phase 4(reconcile 이 잡을 만들 때 활성화 — scheduler/reconcile.py).
"""
from __future__ import annotations

import glob
import os

from ves import config as cfgmod
from ves.adapters import base


def _py(cfg):
    return cfgmod.engine_py(cfg, "brain")


def _scripts(cfg):
    return f"{cfgmod.engine_dir(cfg, 'brain')}/scripts"


def _env(cfg):
    e = dict(os.environ)
    e["AI_VIDEO_ROOT"] = cfgmod.engine_dir(cfg, "ai_video")
    return e


class Ingest:
    """생성물 → fdidiqd provenance 적재 (ingest_aivideo_run.py)."""

    @staticmethod
    def cwd(cfg, job):
        return cfgmod.engine_dir(cfg, "brain")

    @staticmethod
    def env(cfg, job):
        return _env(cfg)

    @staticmethod
    def build_argv(cfg, job):
        p = job["params"]
        run_dir = p.get("run_dir")
        if not run_dir:
            raise base.PermanentError("params.run_dir 없음 — planner/의존 결과 확인")
        return [_py(cfg), f"{_scripts(cfg)}/ingest_aivideo_run.py",
                "--run-dir", run_dir, "--short-label", p.get("short_label", "shorts_1"),
                "--channel", p["channel_name"]]

    @staticmethod
    def parse_result(cfg, job, stdout):
        return {"stdout_tail": (stdout or "")[-400:]}

    @staticmethod
    def classify_error(rc, stderr, stdout):
        return base.classify_by_patterns(stderr, stdout)


class Evaluate:
    """피처 + judge 안전게이트 (evaluate_run.py). judge 는 성과 예측에 쓰지 않는다(D3)."""

    @staticmethod
    def cwd(cfg, job):
        return cfgmod.engine_dir(cfg, "brain")

    @staticmethod
    def env(cfg, job):
        return _env(cfg)

    @staticmethod
    def build_argv(cfg, job):
        p = job["params"]
        return [_py(cfg), f"{_scripts(cfg)}/evaluate_run.py",
                "--run-dir", p["run_dir"], "--channel", p["channel_name"]]

    @staticmethod
    def parse_result(cfg, job, stdout):
        return {"stdout_tail": (stdout or "")[-400:]}

    @staticmethod
    def classify_error(rc, stderr, stdout):
        return base.classify_by_patterns(stderr, stdout)

    @staticmethod
    def post_success(cfg, conn, job, result):
        """안전게이트 통과분을 사람 검수 대기열에 — 검수(D5-①)는 review_queue 로 통합(§8-1)."""
        p = job["params"]
        with conn.cursor() as c:
            c.execute(
                """SELECT 1 FROM public.review_queue
                    WHERE kind='publish_gate' AND work_order_id=%s AND status='waiting'""",
                (job["work_order_id"],))
            if c.fetchone():
                return
            import json
            c.execute(
                """INSERT INTO public.review_queue
                       (kind, work_order_id, job_id, channel_slug, payload)
                   VALUES ('publish_gate', %s, %s, %s, %s::jsonb)""",
                (job["work_order_id"], job["id"], p.get("channel_slug"),
                 json.dumps({"run_id": p.get("run_id"),
                             "preview_key": f"{p.get('run_id')}/preview.mp4",
                             "note": result.get("stdout_tail", "")[-300:]},
                            ensure_ascii=False)))


class Publish:
    """발행 (publish_youtube.py) — R9/지오블락/오채널 게이트는 이 스크립트가 최종 방어선.
    ⚠ 예약공개(publishAt)는 publish_youtube.py 에 아직 없다 — Phase 2 코드 작업(놓친 부분 ④)."""

    @staticmethod
    def cwd(cfg, job):
        return cfgmod.engine_dir(cfg, "brain")

    @staticmethod
    def env(cfg, job):
        return _env(cfg)

    @staticmethod
    def resource(cfg, job):
        return "yt_upload:_global"

    @staticmethod
    def build_argv(cfg, job):
        p = job["params"]
        if p.get("privacy") == "public":
            # R9: public 직행 금지 — RPC 가 걸렀어야 하나 여기서도 차단(이중 방어)
            raise base.PermanentError("R9: publish 잡은 private/unlisted/예약만")
        video = p.get("video_path") or _find_video(cfg, p.get("run_id"), p.get("outdir"))
        if not video:
            raise base.PermanentError(f"영상 파일 못 찾음 (run={p.get('run_id')})")
        argv = [_py(cfg), f"{_scripts(cfg)}/publish_youtube.py",
                "--clip-id", p["clip_id"], "--video", video,
                "--channel", p["channel_name"], "--publish",
                "--privacy", p.get("privacy", "unlisted")]
        if p.get("publish_at"):
            argv += ["--publish-at", p["publish_at"]]   # TODO(Phase 2): 스크립트에 추가 필요
        return argv

    @staticmethod
    def parse_result(cfg, job, stdout):
        return {"stdout_tail": (stdout or "")[-400:]}

    @staticmethod
    def classify_error(rc, stderr, stdout):
        blob = (stderr or "") + (stdout or "")
        if "uploadLimitExceeded" in blob or "quotaExceeded" in blob:
            return "quota"
        return base.classify_by_patterns(stderr, stdout)

    @staticmethod
    def is_already_done(cfg, job):
        return False  # publish_youtube 가 clip 상태로 자체 멱등 처리 — 이중 업로드는 스크립트가 방어


def _find_video(cfg, run_id, outdir):
    if not run_id:
        return None
    base_dir = f"{cfgmod.engine_dir(cfg, 'ai_video')}/{outdir or 'outputs'}/{run_id}"
    vids = [v for v in glob.glob(f"{base_dir}/shorts*.mp4") if "_480" not in v]
    return vids[0] if vids else None
