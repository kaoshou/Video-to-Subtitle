"""Render the real application in an isolated CI virtual display.

Only synthetic fixtures are used. No production module or widget is replaced.
The resulting images are unretouched window-client captures, not mockups.
"""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or platform.system() != 'Linux':
        raise SystemExit('Run this capture only in the isolated Linux screenshot workflow.')

    from PIL import Image, ImageDraw, ImageFont, ImageGrab, PngImagePlugin

    root_path = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root_path))
    import SubtitleTranscriber as application

    output = root_path / 'screenshot-artifacts'
    output.mkdir(exist_ok=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    version = application.get_version()
    metadata = PngImagePlugin.PngInfo()
    for key, value in {
        'Software': f'Video to Subtitle {version}',
        'SourceCommit': commit,
        'Platform': platform.system(),
        'Content': 'Synthetic demonstration; no personal data',
    }.items():
        metadata.add_text(key, value)

    with tempfile.TemporaryDirectory(prefix='subtitle-demo-') as directory:
        demo = Path(directory)
        subtitle = demo / '示範課程.srt'
        subtitle.write_text(
            '1\n00:00:00,000 --> 00:00:04,000\n歡迎使用本地語音轉字幕工具。\n\n'
            '2\n00:00:04,000 --> 00:00:08,000\n加入影片，選擇模型與輸出格式。\n\n'
            '3\n00:00:08,000 --> 00:00:12,000\n完成後，請逐段校對文字與時間軸。\n\n'
            '4\n00:00:12,000 --> 00:00:16,000\n這是示範素材，並非實際轉錄成果。\n',
            encoding='utf-8',
        )
        # A synthetic lecture slide is video INPUT, never an overlay on the UI.
        slide = Image.new('RGB', (960, 540), '#142e4d')
        draw = ImageDraw.Draw(slide)
        font_file = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
        title = ImageFont.truetype(font_file, 44, index=3)
        body = ImageFont.truetype(font_file, 27, index=3)
        draw.rectangle((56, 58, 64, 465), fill='#52c7c0')
        draw.text((98, 75), '示範課程｜字幕製作', font=title, fill='white')
        for y, text in [(195, '01  加入影片與選擇模型'), (265, '02  產生字幕並同步校對'), (335, '03  儲存 SRT / VTT 字幕')]:
            draw.text((98, y), text, font=body, fill='#d8e8f5')
        draw.text((98, 435), '教學示範素材 · 非真實轉錄成果', font=body, fill='#7fbbc9')
        slide.save(demo / 'slide.png')
        video = demo / '示範課程.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(demo / 'slide.png'),
                        '-t', '16', '-r', '5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)

        application.ctk.set_appearance_mode('Light')
        app = application.App()
        errors = []
        app.report_callback_exception = lambda kind, value, traceback: errors.append(f'{kind.__name__}: {value}')
        captures = []

        def settle():
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                app.update()
                time.sleep(0.02)
            if errors:
                raise RuntimeError('\n'.join(errors))

        def capture(window, name):
            window.lift()
            settle()
            assert window.winfo_viewable(), f'{name}: window is not visible'
            x, y = window.winfo_rootx(), window.winfo_rooty()
            width, height = window.winfo_width(), window.winfo_height()
            assert width >= 600 and height >= 500, f'{name}: unexpected size'
            assert x >= 0 and y >= 0 and x + width <= window.winfo_screenwidth() and y + height <= window.winfo_screenheight(), f'{name}: clipped window'
            screenshot = ImageGrab.grab(bbox=(x, y, x + width, y + height), xdisplay=os.environ['DISPLAY'])
            assert screenshot.entropy() > 1.0, f'{name}: blank capture'
            screenshot.save(output / name, pnginfo=metadata)
            captures.append({'file': name, 'width': width, 'height': height, 'title': window.title()})

        try:
            app.geometry('1040x860+80+70')
            app.zh_tw_var.set(True)
            app.prompt_var.set('這是一段示範課程，介紹如何建立與校對繁體中文字幕。')
            app.hotwords_var.set('本機轉錄、字幕校對、EverCam')
            app.add_files_from_paths([str(video)])
            capture(app, 'screenshot_main.png')

            app.geometry('1040x1040+80+70')
            app.btn_toggle_adv.invoke()
            settle()
            app.settings_frame._parent_canvas.yview_moveto(0)
            capture(app, 'screenshot_advanced.png')
            app.btn_toggle_adv.invoke()

            # Hand-written signals demonstrate the real review UI; they are
            # fixture data, never presented as model recognition output.
            review = [dict(start=4, end=8, text='加入影片，選擇模型與輸出格式。',
                           reasons=['辨識信心偏低'])]
            editor = application.SubtitleEditorWindow(app, str(subtitle), str(video),
                                                       review_evidence=review)
            editor.geometry('1320x820+80+70')
            settle()
            assert len(editor.items) == 4, 'Sample subtitle parsing failed'
            editor._select_tree_row(1)
            capture(editor, 'screenshot_editor.png')
            editor.destroy()
            settle()

            app.show_storage_settings()
            capture(app.storage_window, 'screenshot_models.png')
            app.storage_window.destroy()
            settle()

            # Only a temporary private MCP state is used; never change an
            # installed AI client's configuration or start a real model job.
            from mcp_state import State
            from mcp_dialog import MCPSettingsDialog
            state = State(demo / 'mcp-demo')
            state.configure(True, [], access_mode='general')
            state.put('assets', 'demo-video', {'id': 'demo-video',
                'relative': 'Python 程式設計入門.mp4', 'project': {'type': 'mp4'}})
            dialog = MCPSettingsDialog(app, state=state)
            try:
                dialog.top.geometry('940x1040+80+70')
                settle()
                dialog.client.set('codex')
                dialog._notice('示範畫面：使用暫存資料，不影響實際設定與影片。')
                capture(dialog.top, 'screenshot_mcp_connect.png')
                state.put('jobs', 'demo-job', {'id': 'demo-job', 'asset_id': 'demo-video',
                    'kind': 'export', 'state': 'succeeded', 'stage': 'complete', 'elapsed_seconds': 71.9,
                    'result': {'folder': '/示範教材/Python 程式設計入門-web',
                        'index_path': '/示範教材/Python 程式設計入門-web/index.html',
                        'player_type': 'mp4', 'languages': ['zh-TW', 'en', 'ja'],
                        'cue_counts': {'zh-TW': 136, 'en': 136, 'ja': 136},
                        'transcriptions': [{'model': 'large-v3-turbo', 'device': 'cuda', 'backend': 'faster-whisper'}],
                        'review_by_language': {
                            'zh-TW': {'review_count': 4, 'reason_counts': {'辨識信心偏低': 3, '疑似重複內容': 1}},
                            'en': {'review_count': 3, 'reason_counts': {'reading_speed': 3}, 'review_status': 'ai_translation_needs_review'},
                            'ja': {'review_count': 0, 'reason_counts': {}, 'review_status': 'ai_translation_needs_review'}},
                        'unchecked_languages': []}})
                dialog.tabs.set('工作狀態')
                dialog.refresh_jobs()
                capture(dialog.top, 'screenshot_mcp_jobs.png')
                dialog.tabs.set('進階管理')
                capture(dialog.top, 'screenshot_mcp_advanced.png')
            finally:
                for worker in dialog.workers:
                    worker.join(timeout=3)
                dialog.close()
        finally:
            app.destroy()

        (output / 'capture.json').write_text(json.dumps({
            'version': version, 'source_commit': commit, 'platform': platform.system(),
            'method': 'Real application under Xvfb; window client areas; no UI compositing',
            'fixture': 'Synthetic lecture slide, silent video, hand-written subtitles, review signals and private MCP demonstration jobs',
            'capture_run': f'https://github.com/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{os.environ["GITHUB_RUN_ID"]}',
            'captures': captures,
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
