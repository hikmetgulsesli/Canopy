"""Regression tests for channel attachment metadata normalization."""

import unittest
from datetime import datetime, timezone

from canopy.core.channels import Message, MessageType


class TestChannelAttachmentNormalization(unittest.TestCase):
    def test_to_dict_maps_upload_alias_keys_to_canonical_fields(self) -> None:
        msg = Message(
            id='Mabc123',
            channel_id='general',
            user_id='user_1',
            content='',
            message_type=MessageType.FILE,
            created_at=datetime.now(timezone.utc),
            attachments=[
                {
                    'file_id': 'Fmd001',
                    'filename': 'agent_note.md',
                    'content_type': 'text/markdown',
                    'size': '321',
                }
            ],
        )

        payload = msg.to_dict()
        self.assertIn('attachments', payload)
        self.assertEqual(len(payload['attachments']), 1)
        att = payload['attachments'][0]
        self.assertEqual(att.get('id'), 'Fmd001')
        self.assertEqual(att.get('file_id'), 'Fmd001')
        self.assertEqual(att.get('name'), 'agent_note.md')
        self.assertEqual(att.get('type'), 'text/markdown')
        self.assertEqual(att.get('size'), 321)

    def test_to_dict_normalizes_string_attachment_to_file_id(self) -> None:
        msg = Message(
            id='Mabc124',
            channel_id='general',
            user_id='user_1',
            content='',
            message_type=MessageType.FILE,
            created_at=datetime.now(timezone.utc),
            attachments=['Fraw002'],
        )

        payload = msg.to_dict()
        self.assertEqual(len(payload['attachments']), 1)
        att = payload['attachments'][0]
        self.assertEqual(att.get('id'), 'Fraw002')
        self.assertEqual(att.get('file_id'), 'Fraw002')
        self.assertEqual(att.get('name'), 'Fraw002')
        self.assertEqual(att.get('type'), 'application/octet-stream')


if __name__ == '__main__':
    unittest.main()
