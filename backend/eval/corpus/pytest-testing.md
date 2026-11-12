# Pytest: Fixtures, Parametrize, and Markers

Pytest is Python's most widely used test framework. A test is any function whose name starts with test_ in a file whose name starts with test_. Assertions are plain Python assert statements; pytest rewrites them at import time so a failure shows the values on both sides, which is why assert response.status_code == 200 prints the actual code instead of a bare AssertionError.

Fixtures provide setup and teardown. A fixture is a function decorated with @pytest.fixture, and a test requests it by naming it as a parameter. Pytest builds the fixture, passes its return value in, and runs any code after the yield when the test finishes. Fixtures have scopes: function is the default, while session scope builds once per whole run, which is how expensive resources such as a database connection are shared. A fixture can request other fixtures, forming a dependency chain that pytest resolves automatically.

Parametrize runs the same test over many inputs. Decorating a test with @pytest.mark.parametrize("value,expected", [(1, 2), (3, 4)]) runs it once per pair, and each case appears separately in the output, so one failure does not hide the passing cases. It is the standard way to cover edge cases without copy-pasting test functions.

Markers tag tests for selection. @pytest.mark.slow labels a test, and pytest -m "not slow" runs everything except the slow ones. Built-in markers include skip, skipif, and xfail for tests expected to fail. The -k flag filters by name substring, so pytest -k "login" runs only tests with login in the name. Together, markers and -k are how a large suite stays runnable in pieces instead of all or nothing.
