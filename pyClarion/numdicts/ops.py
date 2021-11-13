"""Ops on numerical dictionaries with automdiff support."""


# TODO: GradientOps may not handle defaults correctly! Check and correct. - Can
# by op

__all__ = ["log", "exp", "sigmoid", "tanh", "set_by",
           "sum_by", "max_by", "threshold", "clip", "boltzmann", "keep",
           "drop", "transform_keys", "reduce_sum", "reduce_max", "reduce_min", "by", "merge"]


from .numdicts import (
    D, NumDict, MutableNumDict, record_call, register_op, register_grad
)
from .funcs import isclose, with_default
from typing import Tuple, Union, Dict, List, Callable, Hashable, Container, Any
import math


def log(d: D) -> NumDict:
    """Compute the elementwise natural logarithm of d."""

    return d.log()


def exp(d: D) -> NumDict:
    """Compute the base-e exponential of d."""

    return d.exp()


def sigmoid(d: D) -> NumDict:
    """Apply the logistic function elementwise to d."""

    return 1 / (1 + (-d).exp())


def tanh(d: D) -> NumDict:
    """Apply the tanh function elementwise to d."""

    return (2 * sigmoid(d)) - 1

@register_op
def set_by(
    target: D, source: D, *, keyfunc: Callable[..., Hashable]
) -> NumDict:
    """
    Construct a numdict mapping target keys to matching values in source. 
    
    For each key in source, output[key] = source[keyfunc(key)]. Defaults are
    discarded.
    """

    value = NumDict({k: source[keyfunc(k)] for k in target}, None)
    record_call(set_by, value, (target, source), {"keyfunc": keyfunc})

    return value

@register_grad(set_by)
def _grad_set_by(grads, target, source, *, keyfunc):

    return (grads * NumDict(default=0), sum_by(grads, keyfunc=keyfunc))


@register_op
def threshold(
        d: D, *, th: Union[float, int], keep_default: bool = False) -> NumDict:
    """
    Return a copy of d containing only values above theshold.

    If the default is below or equal threshold it is set to None in the output, unless
    keep default is True.
    """

    mapping = {k: d[k] for k in d if th < d[k]}
    if d.default is not None:
        default = d.default if keep_default or th < d.default else None
    else:  # added this to prevent errors when d.default was none as default was undefined
        default = None
    value = NumDict(mapping, default)
    _kwds = {"th": th}
    record_call(threshold, value, (d,), _kwds)
    return value


@register_grad(threshold)
def _grad_threshold(grads, d, *, th):
    mapping = {k: (th < d[k]) * grads[k] for k in d}
    default = grads.default
    if(d.default == None):
        default = None
    return (NumDict(mapping, default),)


@register_op
def clip(d: D, low: float = None, high: float = None) -> NumDict:
    """
    Return a copy of d with values clipped.

    dtype must define +/- inf values.
    """

    low = low or float("-inf")
    high = high or float("inf")

    mapping = {k: max(low, min(high, d[k])) for k in d}
    value = NumDict(mapping, d.default)
    _kwds = {"low": low, "high": high}
    record_call(clip, value, (d,), _kwds)
    return value


@register_grad(clip)
def _grad_clip(grads, d, *, low, high):
    mapping = {k: (low < d[k] < high)*grads[k] for k in d}
    return (NumDict(mapping, grads.default),)


@register_op
def reduce_sum(d: NumDict, *, key: Hashable = None) -> NumDict:
    kwds = {"key": key}
    result = sum(d.values(), 0)
    if key is None:
        value = NumDict(default=result)
    else:
        value = NumDict({key: result})
    record_call(reduce_sum, value, (d,), kwds)
    return value


@register_grad(reduce_sum)
def _grad_reduce_sum(
    grads: NumDict, d: NumDict, *, key: Hashable = None
) -> Tuple[NumDict, ...]:

    return (d.constant(val=grads.default if key is None else grads[key]),)


@register_op
def reduce_max(d: NumDict, *, key: Hashable = None) -> NumDict:
    kwds = {"key": key}
    result = max(d.values())
    if key is None:
        value = NumDict(default=result)
    else:
        value = NumDict({key: result})
    record_call(reduce_max, value, (d,), kwds)
    return value


@register_grad(reduce_max)  # TODO implement isclose
def _grad_reduce_max(
    grads: NumDict, d: NumDict, *, key: Hashable
) -> Tuple[NumDict, ...]:
    g = grads.default if key is None else grads[key]
    return (g * isclose(d, reduce_max(d)),)


@register_op
def reduce_min(d: NumDict, *, key: Hashable = None) -> NumDict:
    kwds = {"key": key}
    result = min(d.values())
    if key is None:
        value = NumDict(default=result)
    else:
        value = NumDict({key: result})
    record_call(reduce_min, value, (d,), kwds)
    return value


@register_grad(reduce_min)
def _grad_reduce_max(
    grads: NumDict, d: NumDict, *, key: Hashable
) -> Tuple[NumDict, ...]:

    g = grads.default if key is None else grads[key]

    return (g * isclose(d, reduce_min(d)),)

@register_op
def merge(*ds: NumDict) -> NumDict:

    if len(ds) == 0:
        raise ValueError("Nothing to merge.")
    
    if len(set.union(*map(set, ds))) < sum(map(len, ds)):
        raise ValueError("NumDicts are not disjoint")

    data = {}
    for d in ds:
        data.update(d)
    
    if len(set((d.default for d in ds))) == 1:
        default = ds[0].default
    else:
        default = None
    value = NumDict(data, default=default)
    record_call(merge, value, (ds,),{})
    return value

@register_grad(merge)
def _grad_merge(grads: NumDict, *ds: NumDict) -> Tuple[NumDict, ...]:
    return tuple(NumDict({k: grads[k] for k in d}, grads.default) for d in ds)

# We consider a function diffable if
#   1) it is an op
#   2) it is a wrapper for a sequence of ops

def by(
    d: NumDict, 
    *, 
    reducer: Callable[[NumDict, Hashable], NumDict], 
    keyfunc: Callable[[Hashable], Hashable]
) -> NumDict:
    """
    Reduce values in d grouped by keyfunc.

    If reducer is diffable, this function is diffable.

    :param d: The target numdict.
    :param reducer: An op that maps all values of a numdict to a single key.
    :param keyfunc: The grouping function; maps keys to keys.
    """
    
    keys = tuple(set(keyfunc(k) for k in d))
    selectors = ([x for x in d if keyfunc(x) == k] for k in keys)#THIS ISN"T WORKING
    groups = (keep(d, keys=s) for s in selectors)

    return merge(*[reducer(g, key=k) for k, g in zip(keys, groups)])


# This is an op b/c only calls diffable ops
def sum_by(d: NumDict, *, keyfunc: Callable[[Hashable], Hashable]) -> NumDict:

    return by(d, reducer=reduce_sum, keyfunc=keyfunc)

# This is an op b/c only calls diffable ops
def max_by(d: NumDict, *, keyfunc: Callable[[Hashable], Hashable]) -> NumDict:

    return by(d, reducer=reduce_max, keyfunc=keyfunc)

# This is an op b/c only calls diffable ops
def min_by(d: NumDict, *, keyfunc: Callable[[Hashable], Hashable]) -> NumDict:

    return by(d, reducer=reduce_min, keyfunc=keyfunc)

@register_op
def boltzmann(d: D, t: Union[float, int]) -> NumDict:
    """(low < d[k] < high)
    Construct a boltzmann distribution from d with temperature t.

    If d has a default, the returned value will have a default of 0, and, if d
    is empty, the return value will also be empty.
    """
    default = 0 if d.default is not None else None

    if len(d) > 0:
        x = d / t
        x = x - reduce_max(x).default  # softmax(x) = softmax(x + c)
        numerators = x.exp()
        denominator = reduce_sum(numerators).default
        value = with_default(numerators / denominator, default=default)
        kwds = {"t": t}
        record_call(boltzmann, value, (d,), kwds)
        return value
    else:
        value = NumDict(default=default)
        kwds = {"t": t}
        record_call(boltzmann, value, (d,), kwds)
        return NumDict(default=default)


@ register_grad(boltzmann)
def _grad_boltzmann(grads, d, *, t):  # default values?
    if len(d) > 0:
        value = boltzmann(d, t)
        x = d/t
        delta = NumDict(
            {(k, j): grads[k]*(value[k]*((j == k)-value[j])) for j in d for k in d})
        mapping = sum_by(delta, keyfunc=lambda k: k[0])
        return (NumDict(mapping, default=None),)
    else:
        return grads


def keep(
    d: D,
    func: Callable[..., bool] = None,
    keys: Container = None,
    **kwds: Any


) -> NumDict:
    """
    Return a copy of d keeping only the desired keys.

    Keys are kept iff func(key, **kwds) or key in container is True.
    """
    if func is None and keys is None:
        raise ValueError("At least one of func or keys must not be None.")

    mapping = {
        k: d[k] for k in d
        if (
            (func is not None and func(k, **kwds)) or
            (keys is not None and k in keys)
        )
    }
    _kwds = {"func": func, "keys": keys, **kwds}

    value = NumDict(mapping, d.default)
    record_call(keep, value, (d,), _kwds)
    return value


@ register_grad(keep)
def _grad_keep(grads, d, *, func, keys, **kwds):
    mapping = {
        k: (
            (func is not None and func(k, **kwds)) or
            (keys is not None and k in keys)
        )*grads[k]
        for k in d
    }
    #default = grads.default
    # if(d.default == None):
    #    default = None
    return (NumDict(mapping, grads.default),)


def drop(
    d: D,
    func: Callable[..., bool] = None,
    keys: Container = None,
    **kwds: Any
) -> NumDict:
    """
    Return a copy of d dropping unwanted keys.

    Keys are dropped iff func(key, **kwds) or key in container is True.
    """

    if func is None and keys is None:
        raise ValueError("At least one of func or keys must not be None.")
    mapping = {
        k: d[k] for k in d
        if ((func is not None and not func(k, **kwds)) and
            (keys is not None and k not in keys))
    }
    _kwds = {"func": func, "keys": keys, **kwds}  # TODO TEST THIS
    value = NumDict(mapping, d.default)
    record_call(drop, value, (d,), _kwds)
    return value


@ register_grad(drop)
def _grad_drop(grads, d, *, func, keys, **kwds):
    mapping = {
        k: ((func is not None and not func(k, **kwds)) and
            (keys is not None and k not in keys))*grads[k] for k in d
    }
    #default = grads.default
    # if(d.default == None):
    #    default = None
    return (NumDict(mapping, grads.default),)


def transform_keys(d: D, func: Callable[..., Hashable], **kwds) -> NumDict:
    """
    Return a copy of d where each key is mapped to func(key, **kwds).

    Warning: If function is not one-to-one wrt keys, will raise ValueError.
    """

    mapping = {func(k, **kwds): d[k] for k in d}

    if len(d) != len(mapping):
        raise ValueError("Func must be one-to-one on keys of arg d.")
    value = NumDict(mapping, d.default)
    _kwds = {"func": func, **kwds}  # TODO TEST THIS
    record_call(transform_keys, value, (d,), _kwds)
    return value


@ register_grad(transform_keys)
def _grad_transform_keys(grads, d, *, func, **kwds):
    # mapping = {func(k,**kwds): grads[k], **kwds) for k in d}
    mapping = {func(k, **kwds): grads[func(k, **kwds)] for k in d}
    return (NumDict(mapping, grads.default),)
