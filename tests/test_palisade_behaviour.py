import random, tempfile, unittest
from pathlib import Path

from palisade import Database
from palisade.engine import DatabaseError
from palisade.pager import SimulatedCrash
from palisade.sql import SQLError, parse, split_commas


class EngineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(); self.path = Path(self._tmp.name) / 't.pdb'
        self.db = Database(self.path); self.db.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, n INTEGER)')
    def tearDown(self):
        self._tmp.cleanup()

    def test_many_random_inserts_split_pages_and_stay_ordered_across_reopen(self):
        keys = list(range(1, 1201)); random.Random(7).shuffle(keys)
        for k in keys:
            self.db.insert('t', [k, f'row {k} ' + 'x' * 40, k % 7])
        self.assertGreater(len(self.db.btree('t')['levels']), 1, 'expected the tree to grow past one level')
        reopened = Database(self.path)
        self.assertEqual([r['id'] for r in reopened.select('t')], list(range(1, 1201)))
        self.assertEqual(reopened.integrity_check(), [])

    def test_deletes_by_key_and_by_predicate(self):
        for k in range(1, 51): self.db.insert('t', [k, 'n', k % 5])
        self.assertEqual(self.db.delete('t', ('id', '=', 7)), 1)
        self.assertEqual(self.db.delete('t', ('n', '=', 0)), 10)
        self.assertEqual(self.db.delete('t', ('id', '=', 999)), 0)
        self.assertEqual(len(Database(self.path).select('t')), 39)

    def test_where_operators(self):
        for k in range(1, 6): self.db.insert('t', [k, f'n{k}', k])
        q = lambda op, v: [r['id'] for r in self.db.select('t', ('n', op, v))]
        self.assertEqual((q('<', 3), q('>=', 4), q('!=', 2)), ([1, 2], [4, 5], [1, 3, 4, 5]))
        self.assertEqual(self.db.select('t', ('name', '<', 3)), [])  # mixed types never match
        with self.assertRaises(DatabaseError):
            self.db.select('t', ('nope', '=', 1))

    def test_bad_rows_are_rejected_and_leave_the_database_usable(self):
        self.db.insert('t', [1, 'a', 1])
        for bad in ([1, 'dup', 1], ['1', 'a', 1], [2, 3, 1], [3, 'short']):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                self.db.insert('t', bad)
        self.db.insert('t', [2, 'b', 2])
        self.assertEqual([r['id'] for r in Database(self.path).select('t')], [1, 2])
        self.assertEqual(Database(self.path).integrity_check(), [])

    def test_schema_rules(self):
        for sql in ('CREATE TABLE t (id INTEGER PRIMARY KEY)', 'CREATE TABLE u (a TEXT)', 'CREATE TABLE u (a TEXT PRIMARY KEY)',
                    'CREATE TABLE u (a INTEGER PRIMARY KEY, a TEXT)'):
            with self.subTest(sql=sql), self.assertRaises(DatabaseError):
                self.db.execute(sql)

    def test_committed_wal_is_replayed_after_a_crash(self):
        self.db.insert('t', [1, 'before', 1])
        with self.assertRaises(SimulatedCrash):
            self.db.insert('t', [2, 'in flight', 2], crash_after_wal=True)
        recovered = Database(self.path)
        self.assertTrue(recovered.pager.recovery.recovered)
        self.assertEqual([r['name'] for r in recovered.select('t')], ['before', 'in flight'])
        self.assertEqual(recovered.integrity_check(), [])

    def test_torn_wal_is_discarded_not_applied(self):
        self.db.insert('t', [1, 'safe', 1])
        with self.assertRaises(SimulatedCrash):
            self.db.insert('t', [2, 'torn', 2], crash_after_wal=True)
        wal = self.db.pager.wal_path; data = wal.read_bytes(); wal.write_bytes(data[:-3])
        recovered = Database(self.path)
        self.assertTrue(recovered.pager.recovery.discarded_wal)
        self.assertEqual([r['name'] for r in recovered.select('t')], ['safe'])

    def test_corrupted_wal_checksum_is_discarded(self):
        with self.assertRaises(SimulatedCrash):
            self.db.insert('t', [1, 'bad', 1], crash_after_wal=True)
        wal = self.db.pager.wal_path; data = bytearray(wal.read_bytes()); data[40] ^= 0xFF; wal.write_bytes(bytes(data))
        self.assertEqual(Database(self.path).select('t'), [])


class SqlTests(unittest.TestCase):
    def test_strings_keep_commas_quotes_and_unicode(self):
        stmt = parse("INSERT INTO t VALUES (1, 'a, b', 'it\\'s', \"café\")")
        self.assertEqual(stmt.values, [1, 'a, b', "it's", 'café'])
        self.assertEqual(split_commas("1, (2, 3), '4,5'"), ['1', '(2, 3)', "'4,5'"])

    def test_negative_numbers_and_trailing_semicolon(self):
        self.assertEqual(parse('SELECT * FROM t WHERE n >= -3;').where, ('n', '>=', -3))

    def test_unsupported_statements_and_literals_are_errors(self):
        for sql in ('', 'DROP TABLE t', 'SELECT id FROM t', 'DELETE FROM t', 'INSERT INTO t VALUES (1.5)', 'SELECT * FROM t WHERE n = NULL'):
            with self.subTest(sql=sql), self.assertRaises(SQLError):
                parse(sql)


if __name__ == '__main__':
    unittest.main()
