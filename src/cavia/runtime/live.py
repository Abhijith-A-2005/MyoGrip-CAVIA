"""Launch live vision and the arbitration simulator, with detection paused during a grip."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import uuid

from cavia.arbitration.engine import ArbitrationEngine
from cavia.arbitration.preferences import PreferenceStore
from cavia.core.contracts import FsmState
from cavia.fsm.sim import draw, WIDTH, HEIGHT
from .controller import LiveSimApp
from .vision_link import VisionProcess


def draw_live(app, screen, fonts):
    """Reuse the simulator panels and replace mock-only instructions."""
    import pygame

    draw(app, screen, fonts)
    pygame.draw.rect(screen, (24, 26, 31), (24, 16, 480, 24))
    screen.blit(fonts[2].render("CAVIA live vision + arbitration", True, (140, 146, 158)), (24, 18))
    if app.fsm.state is FsmState.HOME:
        pygame.draw.rect(screen, (36, 39, 46), (36, 140, 336, 52))
        screen.blit(fonts[1].render("Waiting for vision lock", True, (140, 146, 158)), (40, 146))
    # The final inherited help line is at y=536 and mentions mock reload.
    pygame.draw.rect(screen, (24, 26, 31), (0, HEIGHT - 26, WIDTH, 26))
    lines = [
        "Q / Esc: quit both windows | Live mode loads menus automatically",
        f"User {app.user} | {app.vision_status}",
        f"Context: {app.request.object}/{app.request.region} | "
        + (app.decision.proposal.policy.value if app.decision else "No actionable menu"),
        "After confirmation: E opens to Full Menu; E again reaches HOME and resumes vision.",
        "Simulation history: 2 s and progress >= 0.2; grasp_success stays unknown.",
    ]
    for i, line in enumerate(lines):
        screen.blit(fonts[2].render(line, True, (210, 215, 225)),
                    (24, HEIGHT - 20 + i * 24))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="1")
    parser.add_argument("--db", default="data/arbitration/demo.sqlite3")
    parser.add_argument(
        "--result-timeout",
        type=float,
        default=2.0,
        help="Seconds without tracker output before marking the retained menu stale",
    )
    parser.add_argument("--log-dir", type=Path, default=Path("data/arbitration/sessions"))
    args = parser.parse_args(argv)
    try:
        import pygame
    except ImportError:
        raise SystemExit('Install dependencies: python -m pip install -e ".[sim,vision]"')

    script = Path(__file__).resolve().parents[1] / "vision" / "objdet.py"
    if not script.is_file():
        raise SystemExit(f"Missing vision script: {script}")
    args.log_dir.mkdir(parents=True, exist_ok=True)
    logfile = args.log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.jsonl"
    with PreferenceStore(args.db) as store, logfile.open("w", encoding="utf-8", buffering=1) as log:
        def audit(event, **data):
            log.write(json.dumps(dict(
                wall=time.time(), ts=time.monotonic(), session=logfile.stem,
                user=app.user, condition="C3_ADAPTIVE", trial=None, type=event, data=data,
            )) + "\n")

        vision = VisionProcess(script)

        app = LiveSimApp(
            ArbitrationEngine(store),
            args.user,
            result_timeout=args.result_timeout,
            audit=audit,
            detection_control=vision.set_paused,
        )
        pygame.init()
        pygame.key.set_repeat()
        try:
            # The actual window can be resized freely.
            window = pygame.display.set_mode(
                (WIDTH, HEIGHT + 100),
                pygame.RESIZABLE,
            )

            # Keep the existing drawing coordinates on a separate surface.
            screen = pygame.Surface((WIDTH, HEIGHT + 100)).convert()
            pygame.display.set_caption("CAVIA live vision + arbitration simulation")
            fonts = (pygame.font.Font(None, 40), pygame.font.Font(None, 30), pygame.font.Font(None, 22))
            clock = pygame.time.Clock()
            vision.start()
            audit("session_started", user=app.user, database=args.db)
            while not app.quit:
                # Drain even while frozen so old detections cannot accumulate.
                result = vision.latest()
                if result is not None:
                    app.receive(result)
                app.check_source(exited=vision.exited)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        app.quit = True
                    elif event.type == pygame.VIDEORESIZE:
                        window = pygame.display.set_mode(
                            (max(1, event.w), max(1, event.h)),
                            pygame.RESIZABLE,
                        )
                    elif event.type == pygame.KEYDOWN:
                        app.key_down(pygame.key.name(event.key))
                    elif event.type == pygame.KEYUP:
                        app.key_up(pygame.key.name(event.key))
                    elif event.type == pygame.WINDOWFOCUSLOST:
                        app.focus_lost()
                if app.quit:
                    break
                app.step(clock.tick(60) / 1000.0)

                if vision.control_error:
                    app.vision_status = (
                        "Vision control failed; context retained. Restart CAVIA."
                    )

                draw_live(app, screen, fonts)

                # Fit the complete interface inside the current window.
                window_width, window_height = window.get_size()
                scale = min(
                    window_width / screen.get_width(),
                    window_height / screen.get_height(),
                )
                scaled_size = (
                    max(1, int(screen.get_width() * scale)),
                    max(1, int(screen.get_height() * scale)),
                )
                preview = pygame.transform.smoothscale(screen, scaled_size)

                # Centre the interface without stretching its proportions.
                window.fill((24, 26, 31))
                window.blit(
                    preview,
                    (
                        (window_width - scaled_size[0]) // 2,
                        (window_height - scaled_size[1]) // 2,
                    ),
                )
                pygame.display.flip()
                app.mark_rendered()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                app.cancel_pending()
                audit("session_closed")
            finally:
                vision.close()
                pygame.quit()


if __name__ == "__main__":
    main()