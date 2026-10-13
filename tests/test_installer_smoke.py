import os
import unittest


class InstallerSmokeTools(unittest.TestCase):
    def test_clean_environment_does_not_depend_on_host_python_or_ffmpeg(self):
        from scripts.smoke_windows_installer import isolated_environment
        source = {'SystemRoot': r'C:\Windows', 'PATH': r'C:\Python;C:\ffmpeg',
                  'PYTHONHOME': r'C:\Python', 'PYTHONPATH': r'C:\site-packages',
                  'LOCALAPPDATA': r'C:\User\AppData\Local', 'OTHER': 'keep'}
        result = isolated_environment(source)
        self.assertEqual(result['PATH'], os.path.join(r'C:\Windows', 'System32'))
        self.assertNotIn('PYTHONHOME', result)
        self.assertNotIn('PYTHONPATH', result)
        self.assertEqual(result['OTHER'], 'keep')
        self.assertEqual(source['PYTHONHOME'], r'C:\Python')

    def test_first_launch_is_reported_separately_from_repeat_median(self):
        from scripts.smoke_windows_installer import summarize_startup
        self.assertEqual(summarize_startup([12.0, 5.0, 3.0]),
                         {'first_gui_launch_seconds': 12.0,
                          'repeat_median_seconds': 4.0,
                          'samples_seconds': [12.0, 5.0, 3.0]})

    def test_insufficient_samples_cannot_be_reported_as_success(self):
        from scripts.smoke_windows_installer import summarize_startup
        for samples in ([], [1.0]):
            with self.assertRaises(ValueError):
                summarize_startup(samples)
