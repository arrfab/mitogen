import pickle
import sys

import unittest2

import mitogen.core

import testlib
import plain_old_module


class ConstructorTest(testlib.TestCase):
    klass = mitogen.core.CallError

    def test_string_noargs(self):
        e = self.klass('%s%s')
        self.assertEquals(e.args[0], '%s%s')
        self.assertTrue(isinstance(e.args[0], mitogen.core.UnicodeType))

    def test_string_args(self):
        e = self.klass('%s%s', 1, 1)
        self.assertEquals(e.args[0], '11')
        self.assertTrue(isinstance(e.args[0], mitogen.core.UnicodeType))

    def test_from_exc(self):
        ve = plain_old_module.MyError('eek')
        e = self.klass(ve)
        self.assertEquals(e.args[0], 'plain_old_module.MyError: eek')
        self.assertTrue(isinstance(e.args[0], mitogen.core.UnicodeType))

    def test_form_base_exc(self):
        ve = SystemExit('eek')
        e = self.klass(ve)
        self.assertEquals(e.args[0],
            # varies across 2/3.
            '%s.%s: eek' % (type(ve).__module__, type(ve).__name__))
        self.assertTrue(isinstance(e.args[0], mitogen.core.UnicodeType))

    def test_from_exc_tb(self):
        try:
            raise plain_old_module.MyError('eek')
        except plain_old_module.MyError:
            ve = sys.exc_info()[1]
            e = self.klass(ve)

        self.assertTrue(e.args[0].startswith('plain_old_module.MyError: eek'))
        self.assertTrue(isinstance(e.args[0], mitogen.core.UnicodeType))
        self.assertTrue('test_from_exc_tb' in e.args[0])

    def test_bytestring_conversion(self):
        e = self.klass(mitogen.core.b('bytes'))
        self.assertEquals(u'bytes', e.args[0])
        self.assertTrue(isinstance(e.args[0], mitogen.core.UnicodeType))

    def test_reduce(self):
        e = self.klass('eek')
        func, (arg,) = e.__reduce__()
        self.assertTrue(func is mitogen.core._unpickle_call_error)
        self.assertEquals(arg, e.args[0])


class UnpickleCallErrorTest(testlib.TestCase):
    func = staticmethod(mitogen.core._unpickle_call_error)

    def test_not_unicode(self):
        self.assertRaises(TypeError,
            lambda: self.func(mitogen.core.b('bad')))

    def test_oversized(self):
        self.assertRaises(TypeError,
            lambda: self.func(mitogen.core.b('b'*10001)))

    def test_reify(self):
        e = self.func(u'some error')
        self.assertEquals(mitogen.core.CallError, type(e))
        self.assertEquals(1, len(e.args))
        self.assertEquals(mitogen.core.UnicodeType, type(e.args[0]))
        self.assertEquals(u'some error', e.args[0])


class PickleTest(testlib.TestCase):
    klass = mitogen.core.CallError

    def test_string_noargs(self):
        e = self.klass('%s%s')
        e2 = pickle.loads(pickle.dumps(e))
        self.assertEquals(e2.args[0], '%s%s')

    def test_string_args(self):
        e = self.klass('%s%s', 1, 1)
        e2 = pickle.loads(pickle.dumps(e))
        self.assertEquals(e2.args[0], '11')

    def test_from_exc(self):
        ve = plain_old_module.MyError('eek')
        e = self.klass(ve)
        e2 = pickle.loads(pickle.dumps(e))
        self.assertEquals(e2.args[0], 'plain_old_module.MyError: eek')

    def test_from_exc_tb(self):
        try:
            raise plain_old_module.MyError('eek')
        except plain_old_module.MyError:
            ve = sys.exc_info()[1]
            e = self.klass(ve)

        e2 = pickle.loads(pickle.dumps(e))
        self.assertTrue(e2.args[0].startswith('plain_old_module.MyError: eek'))
        self.assertTrue('test_from_exc_tb' in e2.args[0])


if __name__ == '__main__':
    unittest2.main()
