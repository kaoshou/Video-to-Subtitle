import unittest
from mcp_state import MCPError
from test_mcp_service import ServiceFixture


class QualityTests(unittest.TestCase):
    def report(self, cues, translations, **kwargs):
        from mcp_translation import quality_report
        return quality_report(cues, translations, 'en', 'fr', [], **kwargs)

    def test_long_fast_unchanged_and_glossary_are_advisory_without_timing_edits(self):
        from mcp_translation import quality_report
        text = 'Python is used here to explain a complete introductory programming example.'
        cues = [{'cue_id': 'one', 'start': .123, 'end': 1.456, 'text': text}]
        report = quality_report(cues, {'one': text}, 'en', 'fr', [{'source': 'Python', 'target': '巨蟒'}])
        self.assertEqual(report['review_count'], 1)
        self.assertEqual(set(report['items'][0]['reasons']), {'reading_speed', 'possibly_untranslated', 'glossary_mismatch'})
        self.assertEqual(report['items'][0]['start'], .123)
        self.assertEqual(report['items'][0]['end'], 1.456)
        self.assertEqual(cues[0]['text'], text)

    def test_same_language_short_names_and_term_substrings_are_not_mistranslations(self):
        from mcp_translation import quality_report
        cues = [{'cue_id': 'one', 'start': 0, 'end': 20, 'text': 'community Python'}]
        report = quality_report(cues, {'one': 'community Python'}, 'en', 'en-US',
                                [{'source': 'Unity', 'target': '統一'}])
        self.assertEqual(report['review_count'], 0)
        cues[0]['text'] = 'Python'
        self.assertEqual(quality_report(cues, {'one': 'Python'}, 'en', 'ja', [])['review_count'], 0)

    def test_all_counts_survive_detail_pagination_and_unicode_is_counted_as_text(self):
        cues = [{'cue_id': str(i), 'start': i * 10, 'end': i * 10 + 10, 'text': 'Original'} for i in range(205)]
        translations = {cue['cue_id']: '字幕' * 70 for cue in cues}
        report = self.report(cues, translations)
        self.assertEqual(report['review_count'], 205)
        self.assertEqual(report['reason_counts']['long_text'], 205)
        self.assertEqual(len(report['items']), 200)
        self.assertTrue(report['truncated'])
        tail = self.report(cues, translations, cursor=200, limit=50)
        self.assertEqual(len(tail['items']), 5)
        self.assertIsNone(tail['next_cursor'])

    def test_missing_or_empty_text_is_still_a_hard_error(self):
        cues = [{'cue_id': 'one', 'start': 0, 'end': 1, 'text': 'Original'}]
        for translations in ({}, {'one': ''}):
            with self.subTest(translations=translations), self.assertRaises(MCPError):
                self.report(cues, translations)


class QualityServiceTests(ServiceFixture):
    def test_quality_persists_after_restart_and_report_cannot_bypass_access(self):
        source = self.imported()
        draft = self.service.call('prepare_translation', {'source_id': source['source_id'],
            'revision': source['revision'], 'language': 'fr', 'glossary': 'keep course terminology',
            'glossary_terms': [{'source': 'First', 'target': 'Premier'}], 'request_id': 'quality-draft'})
        batch = self.service.call('get_translation_batch', {'draft_id': draft['draft_id'],
            'batch_id': draft['batches'][0]['batch_id']})
        self.assertEqual(batch['glossary_terms'], [{'source': 'First', 'target': 'Premier'}])
        entries = [{'cue_id': cue['cue_id'], 'text': 'x' * 130 if i == 0 else 'Second'}
                   for i, cue in enumerate(batch['cues'])]
        self.service.call('submit_translation_batch', {'draft_id': draft['draft_id'], 'batch_id': batch['batch_id'],
            'revision': draft['revision'], 'translations': entries, 'request_id': 'quality-submit'})
        args = {'draft_id': draft['draft_id'], 'request_id': 'quality-finalize'}
        finalized = self.service.call('finalize_translation', args)
        self.assertEqual(finalized['review']['review_count'], 1)
        self.assertEqual(finalized['review']['reason_counts']['glossary_mismatch'], 1)
        self.service.close(); self.service = self.api.Service(self.state)
        self.assertEqual(self.service.call('finalize_translation', args), finalized)
        report = self.service.call('read_review', {'track_id': finalized['track_id'], 'limit': 1})
        self.assertEqual(report['items'][0]['cue_id'], entries[0]['cue_id'])
        self.assertIn('long_text', report['items'][0]['reasons'])
        self.state.disable()
        with self.assertRaises(MCPError):
            self.service.call('read_review', {'track_id': finalized['track_id']})
