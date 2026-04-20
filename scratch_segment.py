import re

class StreamingSegmenter:
    def __init__(self, max_chars=35, gap_threshold=0.8):
        self.max_chars = max_chars
        self.gap_threshold = gap_threshold
        self.current_piece = None
        self.strong_punctuations = ["。", "！", "？", ".", "?", "!", "\n"]
        self.all_punctuations = ["，", "。", "！", "？", "；", "、", ",", ".", "?", ";", "!", "\n"]

    def process_segment(self, segment):
        results = []
        pieces = []
        text = segment['text'].strip()
        start = segment['start']
        end = segment['end']
        
        chunks = re.split(r'([，。！？；、,.?;!\n])', text)
        merged_chunks = []
        for i in range(0, len(chunks)-1, 2):
            chunk_text = chunks[i].strip()
            delimiter = chunks[i+1]
            if chunk_text:
                merged_chunks.append(chunk_text + delimiter)
            elif merged_chunks:
                 merged_chunks[-1] += delimiter
        if len(chunks) % 2 == 1 and chunks[-1].strip():
            merged_chunks.append(chunks[-1].strip())
        
        total_len = sum(len(c) for c in merged_chunks)
        if total_len == 0:
            return []
        
        curr_start = start
        seg_duration = end - start
        for c in merged_chunks:
            ratio = len(c) / total_len
            duration = seg_duration * ratio
            pieces.append({
                'start': curr_start,
                'end': curr_start + duration,
                'text': c
            })
            curr_start += duration
                
        for p in pieces:
            p_text = p['text'].strip()
            if not p_text:
                continue
                
            if not self.current_piece:
                self.current_piece = {'start': p['start'], 'end': p['end'], 'text': p['text']}
                continue
                
            gap = p['start'] - self.current_piece['end']
            combined_text = self.current_piece['text'] + (" " if p_text.isascii() and self.current_piece['text'].isascii() else "") + p['text']
            
            # check the PUNC at the end of current_piece
            has_strong_punc = any(self.current_piece['text'].endswith(punc) for punc in self.strong_punctuations)
            has_any_punc = any(self.current_piece['text'].endswith(punc) for punc in self.all_punctuations)
            
            should_break = False
            
            # Evaluate using string length mapping
            if len(combined_text) > self.max_chars and has_any_punc:
                should_break = True
            elif len(combined_text) > self.max_chars + 15: # Forced break
                should_break = True
            elif gap > self.gap_threshold:
                should_break = True
            elif has_strong_punc and len(self.current_piece['text']) > 15:
                should_break = True
                
            if should_break:
                results.append(self.current_piece)
                self.current_piece = {'start': p['start'], 'end': p['end'], 'text': p['text']}
            else:
                self.current_piece['end'] = p['end']
                self.current_piece['text'] = combined_text
                
        return results

    def flush(self):
        if self.current_piece:
            res = [self.current_piece]
            self.current_piece = None
            return res
        return []

test_segs = [
    {
        'start': 0.0, 'end': 3.0, 
        'text': '你好，歡迎來到今天的新聞。'
    },
    {
        'start': 3.1, 'end': 8.0,
        'text': '我們今天要播報的是一件非常重要而且驚人的消息，那就是昨天晚上在台北市發生了一起重大的車禍，造成了很多台車輛的損毀。'
    },
    {
        'start': 8.1, 'end': 9.0,
        'text': '對吧？'
    },
    {
        'start': 9.1, 'end': 10.0,
        'text': '是的。'
    }
]

segmenter = StreamingSegmenter()
final_res = []
for s in test_segs:
    final_res.extend(segmenter.process_segment(s))
final_res.extend(segmenter.flush())

for r in final_res:
    print(f"[{r['start']:.1f} - {r['end']:.1f}] {r['text']}")

