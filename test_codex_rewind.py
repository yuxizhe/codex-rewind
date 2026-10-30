import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('rewind', Path(__file__).with_name('codex-rewind.py'))
rewind = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rewind)


class CompatibilityTests(unittest.TestCase):
    def test_expected_contract(self):
        self.assertTrue(rewind.compatible({'required': ['beforeTurnId', 'threadId']}))

    def test_reject_changed_contract(self):
        for fields in ([], ['threadId', 'numTurns'], ['threadId', 'beforeTurnId', 'extra']):
            self.assertFalse(rewind.compatible({'required': fields}))

class SelectionTests(unittest.TestCase):
    def test_pagination_and_selection(self):
        from unittest.mock import Mock, patch
        server = Mock()
        server.call.side_effect = [dict(data=[dict(id='first')], nextCursor='next'), dict(data=[dict(id='second')])]
        with patch('builtins.input', side_effect=['99', 'n', '1']), patch('builtins.print'):
            selected = rewind.choose(server, 'thread/list', {}, 'title', lambda row: row['id'])
        self.assertEqual(selected['id'], 'second')
        self.assertEqual(server.call.call_args.args[1]['cursor'], 'next')

    def test_cancel(self):
        from unittest.mock import Mock, patch
        server = Mock()
        server.call.return_value = dict(data=[])
        with patch('builtins.input', return_value='q'), patch('builtins.print'), self.assertRaises(SystemExit):
            rewind.choose(server, 'thread/list', {}, 'title', str)

    def test_user_message_preview(self):
        self.assertEqual(rewind.turn_label(dict(id='t1', items=[dict(type='userMessage', content=[dict(type='text', text='hello\nworld')])])), 'hello world  [t1]')

class RevertTests(unittest.TestCase):
    def test_resume_before_revert(self):
        from unittest.mock import Mock, call
        server = Mock()
        server.call.side_effect = [dict(thread=dict(id='target', status=dict(type='idle'))), dict(thread=dict(id='target'))]
        rewind.load_for_revert(server, 'target')
        self.assertEqual(server.call.call_args_list, [
            call('thread/resume', dict(threadId='target', excludeTurns=True))])

    def test_active_target_is_not_reverted(self):
        from unittest.mock import Mock
        server = Mock()
        server.call.return_value = dict(thread=dict(id='target', status=dict(type='active')))
        with self.assertRaises(RuntimeError):
            rewind.load_for_revert(server, 'target')
        self.assertEqual(server.call.call_count, 1)

    def test_writer_conflict_is_actionable(self):
        from unittest.mock import Mock
        server = Mock()
        server.call.side_effect = RuntimeError('thread already has an active writer')
        with self.assertRaisesRegex(RuntimeError, '尚未创建新备份'):
            rewind.load_for_revert(server, 'target')
        self.assertEqual(server.call.call_count, 1)

class InterruptTests(unittest.TestCase):
    def test_idle_is_untouched(self):
        from unittest.mock import Mock
        server = Mock()
        server.call.return_value = dict(thread=dict(status=dict(type='idle')))
        rewind.stop_target_turn(server, 'target')
        self.assertEqual(server.call.call_count, 1)

    def test_interrupt_only_selected_turn(self):
        from unittest.mock import Mock, call
        server = Mock()
        server.call.side_effect = [dict(thread=dict(status=dict(type='active'))),
                                   dict(data=[dict(id='running', status='inProgress')]), {},
                                   dict(thread=dict(status=dict(type='idle')))]
        rewind.stop_target_turn(server, 'target')
        self.assertIn(call('turn/interrupt', dict(threadId='target', turnId='running')), server.call.call_args_list)
