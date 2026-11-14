import tempfile
import unittest
from pathlib import Path
from mcp_state import State, MCPError
from mcp_jobs import clear_completed_jobs, dismiss_job, filter_jobs, diagnostic_report


class HistoryTests(unittest.TestCase):
    def test_dismiss_persists_but_running_job_cannot_be_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State(Path(folder) / 'state')
            state.configure(True, [], access_mode='general')
            key = 'a' * 32
            state.put('jobs', key, {'id':key, 'state':'running'})
            with self.assertRaises(MCPError): dismiss_job(state, key)
            self.assertFalse(state.get('jobs', key).get('hidden_from_history'))
            state.put('jobs', key, {'id':key, 'state':'failed', 'result':{'track_id':'kept'}})
            dismiss_job(state, key)
            reopened = State(state.path)
            self.assertEqual(filter_jobs(reopened.records('jobs')), [])
            self.assertEqual(reopened.get('jobs', key)['result']['track_id'], 'kept')

    def test_failed_filter_and_diagnostic_omit_private_content(self):
        jobs = [{'state':s} for s in ('running', 'succeeded', 'failed', 'interrupted', 'cancelled')]
        self.assertEqual([j['state'] for j in filter_jobs(jobs, '失敗／中斷')], ['failed', 'interrupted'])
        report = diagnostic_report({'id':'a'*32, 'state':'failed', 'arguments':{'settings':{
            'model':'large-v3-turbo', 'hotwords':'PRIVATE', 'cache_dir':'PRIVATE', 'initial_prompt':'PRIVATE'}},
            'error':{'code':'JOB_FAILED', 'message':'PRIVATE', 'diagnostic':{
                'exception':'OSError', 'frames':[{'file':'C:\\PRIVATE\\mcp_service.py','line':12,'function':'_transcribe'}]}},
            'result':{'text':'PRIVATE', 'folder':'PRIVATE'}})
        self.assertNotIn('PRIVATE', str(report))
        self.assertIsNone(report['job']['actual_transcription'])
        self.assertEqual(report['job']['requested_settings']['model'], 'large-v3-turbo')
        self.assertEqual(report['job']['diagnostic']['frames'][0]['file'], 'mcp_service.py')

    def test_clear_preserves_results_active_jobs_and_retry_lookup(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State(Path(folder) / 'state')
            state.configure(True, [], access_mode='general')
            for index, status in enumerate(('succeeded', 'running', 'failed')):
                key = f'{index:032x}'
                state.put('jobs', key, {'id': key, 'state': status, 'result': {'track_id': 'kept'}})
            self.assertEqual(clear_completed_jobs(state), 1)
            self.assertEqual(clear_completed_jobs(state), 0)
            jobs = state.records('jobs')
            self.assertEqual(len(jobs), 3)
            self.assertEqual(sum(bool(j.get('hidden_from_history')) for j in jobs), 1)
            self.assertTrue(all(j['result']['track_id'] == 'kept' for j in jobs))
