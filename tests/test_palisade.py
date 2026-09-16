import tempfile
import unittest
from pathlib import Path
from palisade import Database

class PalisadeTests(unittest.TestCase):
    def test_create_insert_select_delete_and_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'demo.pdb'
            db = Database(path)
            db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);')
            db.execute("INSERT INTO users VALUES (1, 'Ada');")
            db.execute("INSERT INTO users VALUES (2, 'Grace');")
            rows = db.execute('SELECT * FROM users;')['rows']
            self.assertEqual([r['name'] for r in rows], ['Ada', 'Grace'])
            result = db.execute('DELETE FROM users WHERE id = 1;')
            self.assertIn('1 row', result['message'])
            reopened = Database(path)
            rows = reopened.execute('SELECT * FROM users;')['rows']
            self.assertEqual(rows, [{'id': 2, 'name': 'Grace'}])
            self.assertEqual(reopened.integrity_check(), [])

    def test_custom_format_has_expected_magic(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'demo.pdb'
            Database(path)
            self.assertEqual(path.read_bytes()[:8], b'PALISADE')

if __name__ == '__main__':
    unittest.main()
