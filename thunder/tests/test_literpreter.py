from collections.abc import Iterable, Iterator, Sequence
from functools import partial, wraps
from itertools import product

import sys
import dis
from collections.abc import Callable

import pytest
import torch
from torch.testing import assert_close

import thunder
from thunder.core.jit import is_jitting, jit, JITError

from thunder.core.jit_ext import litjit
import thunder.clang as clang
import thunder.torch as ltorch
import thunder.core.prims as prims

#
# Test suite for the litjit extension of the Python interpreter
#


def skipif_python_3_11_plus(f):
    if sys.version_info >= (3, 11):
        return pytest.mark.skip(f, reason=f"not yet implemented for Python 3.11+, got {sys.version_info=}")
    return f


def test_binary_add_tensors():
    def foo(a, b):
        return a + b

    jfoo = litjit(foo)

    a = torch.randn((2, 2), device="cpu")
    b = torch.randn((2, 2), device="cpu")

    actual = jfoo(a, b)
    expected = foo(a, b)

    assert_close(actual, expected)


def test_torch_add_tensors():
    def foo(a, b):
        return torch.add(a, b)

    jfoo = litjit(foo)

    a = torch.randn((2, 2), device="cpu")
    b = torch.randn((2, 2), device="cpu")

    actual = jfoo(a, b)
    expected = foo(a, b)

    assert_close(actual, expected)


def test_torch_add_tensors_closure():
    def foo(a, b):
        c = a + b

        def bar():
            return torch.add(c, 1)

        return bar()

    jfoo = litjit(foo)

    a = torch.randn((2, 2), device="cpu")
    b = torch.randn((2, 2), device="cpu")

    actual = jfoo(a, b)
    expected = foo(a, b)

    assert_close(actual, expected)


def test_intermediate_torch_operations():
    def foo(a, b):
        c = a + b
        d = torch.sub(c, b)
        e = torch.mul(d, a)
        f = torch.matmul(e, c)
        g = [e, f]
        return torch.cat(g)

    jfoo = litjit(foo)

    a = torch.randn((2, 2), device="cpu")
    b = torch.randn((2, 2), device="cpu")

    actual = jfoo(a, b)
    expected = foo(a, b)

    assert_close(actual, expected)


def test_cache_basic():
    def foo(a, b):
        return a + b

    jfoo = litjit(foo)

    a = torch.randn((2, 2), device="cpu")
    b = torch.randn((2, 2), device="cpu")

    expected = foo(a, b)
    actual = jfoo(a, b)
    assert_close(expected, actual)
    assert thunder.cache_misses(jfoo) == 1
    assert thunder.cache_hits(jfoo) == 0

    expected = foo(a, b)
    actual = jfoo(a, b)
    assert_close(expected, actual)
    assert thunder.cache_misses(jfoo) == 1
    assert thunder.cache_hits(jfoo) == 1

    # Tests rank changing
    a = torch.randn((2), device="cpu")

    expected = foo(a, b)
    actual = jfoo(a, b)
    assert_close(expected, actual)
    assert thunder.cache_misses(jfoo) == 2
    assert thunder.cache_hits(jfoo) == 1

    expected = foo(a, b)
    actual = jfoo(a, b)
    assert_close(expected, actual)
    assert thunder.cache_misses(jfoo) == 2
    assert thunder.cache_hits(jfoo) == 2

    # Tests dtype changing
    a = torch.randn((2, 2), device="cpu", dtype=torch.bfloat16)
    b = torch.randn((2, 2), device="cpu", dtype=torch.bfloat16)

    expected = foo(a, b)
    actual = jfoo(a, b)
    assert_close(expected, actual)
    assert thunder.cache_misses(jfoo) == 3
    assert thunder.cache_hits(jfoo) == 2

    expected = foo(a, b)
    actual = jfoo(a, b)
    assert_close(expected, actual)
    assert thunder.cache_misses(jfoo) == 3
    assert thunder.cache_hits(jfoo) == 3

    # Tests shape changing
    a = torch.randn((2, 1), device="cpu", dtype=torch.bfloat16)
    b = torch.randn((2, 1), device="cpu", dtype=torch.bfloat16)

    expected = foo(a, b)
    actual = jfoo(a, b)
    assert_close(expected, actual)
    assert thunder.cache_misses(jfoo) == 4
    assert thunder.cache_hits(jfoo) == 3

    expected = foo(a, b)
    actual = jfoo(a, b)
    assert_close(expected, actual)
    assert thunder.cache_misses(jfoo) == 4
    assert thunder.cache_hits(jfoo) == 4


@pytest.mark.xfail(reason="https://github.com/Lightning-AI/lightning-thunder/issues/1933", raises=BaseException)
def test_add_numbers():
    def foo(a, b):
        return a + b

    jfoo = litjit(foo)

    a = 2
    b = 3

    actual = jfoo(a, b)
    expected = foo(a, b)

    assert_close(actual, expected)


_test_add_global_global = 2


@pytest.mark.xfail(reason="https://github.com/Lightning-AI/lightning-thunder/issues/1935", raises=BaseException)
def test_global_fails():
    def foo():
        return _test_add_global_global

    jfoo = litjit(foo)

    with pytest.raises(NotImplementedError):
        jfoo()


@pytest.mark.xfail(reason="https://github.com/Lightning-AI/lightning-thunder/issues/1936", raises=BaseException)
def test_nonlocal_outside_interpreter_fails():
    def foo():
        x = 3

        def bar():
            nonlocal x
            x = 4

        jbar = litjit(bar)

        jbar()

        return x

    with pytest.raises(NotImplementedError):
        foo()
