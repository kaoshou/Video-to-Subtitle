"""Human-readable local job summaries, without exposing opaque IDs by default."""
from pathlib import Path
import math
from mcp_progress import valid_progress

STATES = {'queued':'等待處理', 'preparing':'準備中', 'running':'處理中',
          'validating':'檢查成果', 'publishing':'儲存成果', 'cancelling':'取消中',
          'succeeded':'已完成', 'failed':'未完成', 'cancelled':'已取消', 'interrupted':'已中斷'}
STAGES = {'snapshot':'建立工作副本', 'transcription':'辨識語音並產生字幕',
          'model':'準備辨識模型', 'audio':'處理音訊', 'recognition':'辨識語音',
          'output':'整理字幕', 'retry':'調整批次後重新辨識',
          'subtitle':'檢查字幕格式', 'export':'建立網頁播放器', 'package':'整理播放器檔案',
          'complete':'處理完成'}
ERRORS = {'MODEL_DOWNLOAD_REQUIRED':'所選模型尚未備妥，請先到模型儲存管理完成下載。',
          'MODEL_ACCESS_ERROR':'目前無法讀取模型，請檢查模型儲存位置與權限。',
          'SOURCE_CHANGED':'來源檔案已變更，請回到 AI 對話重新選取來源。',
          'PROJECT_CHANGED':'課程專案已變更，請重新選取專案再匯出。',
          'ROOT_NOT_ALLOWED':'來源資料夾目前未獲允許，請檢查 AI 連接設定。',
          'DISK_FULL':'儲存空間不足，請先釋出磁碟空間後再試。',
          'INVALID_SUBTITLE':'字幕格式無法讀取，請檢查 SRT／VTT 內容並重新匯入。',
          'TRANSLATION_INCOMPLETE':'選定語言尚未翻譯完成，請先回到 AI 完成翻譯。',
          'CANCELLED':'工作已取消，原始檔案保留。'}


def job_card(job):
    result = job.get('result', {})
    kind = '建立網頁播放器' if job.get('kind') == 'export' or result.get('index_path') else '產生字幕'
    state = job.get('state', '')
    title = job.get('display_name') or (Path(result['source_path']).name if result.get('source_path') else kind)
    description = STAGES.get(job.get('stage'), '正在處理，請稍候。')
    if state == 'succeeded':
        description = ('播放器已建立，可直接開啟觀看。' if result.get('index_path') else
                       f"已產生 {result['cue_count']} 段字幕，可回到 AI 繼續翻譯或輸出網頁。" if 'cue_count' in result else
                       '工作已完成，可回到 AI 對話查看成果。')
    elif state == 'failed':
        description = ERRORS.get(job.get('error', {}).get('code'), '工作未完成，請展開詳細資訊查看原因。')
    elif state in ('cancelled', 'interrupted'):
        description = '原始檔案保留。需要重新處理時，請回到 AI 對話提出新工作。'
    elif state == 'queued':
        description = '已接受工作，等待前一項工作釋放運算資源。'
    reports = ([result['transcription']] if result.get('transcription') else result.get('transcriptions', []))
    model_lines = []
    for info in reports:
        device = 'MLX' if info['device'] in ('mlx', 'mps') else info['device'].upper()
        model_lines.append(f"轉錄模型：{info['model']} · {device}")
    technical = f"工作代碼：{job['id']}\n狀態代碼：{state} · {job.get('stage', '')}"
    if result.get('folder'):
        technical += '\n輸出位置：' + result['folder']
    if job.get('error'):
        technical += '\n' + job['error'].get('code', '') + ': ' + job['error'].get('message', '')[:1000]
    for info in reports:
        technical += '\n辨識引擎：' + info.get('backend', '未記錄')
    project = {'opencam':'OpenCam', 'evercam':'EverCam', 'mp4':'MP4'}.get(
        result.get('player_type') or job.get('project_type'), '')
    progress = job.get('progress')
    fraction, progress_text = None, ''
    if state not in ('succeeded', 'failed', 'cancelled', 'interrupted') and valid_progress(progress):
        fraction = progress['fraction']
        phase = STAGES.get(progress['stage'], '處理中')
        progress_text = phase + (f' · {fraction * 100:.0f}%' if fraction is not None else ' · 處理中')
    elapsed = job.get('elapsed_seconds')
    timing_text = ''
    if type(elapsed) in (float, int) and math.isfinite(elapsed) and elapsed >= 0:
        minutes, seconds = divmod(round(elapsed), 60)
        timing_text = f'處理耗時：{minutes} 分 {seconds:02} 秒' if minutes else f'處理耗時：{seconds} 秒'
    return {'title':title, 'kind':kind + (' · ' + project if project else ''),
            'progress_fraction': fraction, 'progress_text': progress_text, 'timing_text': timing_text,
            'status':STATES.get(state, '狀態待確認'), 'description':description,
            'models':model_lines, 'technical':technical,
            'can_open':state == 'succeeded' and bool(result.get('index_path')),
            'can_cancel':state not in ('succeeded', 'failed', 'cancelled', 'interrupted')}
