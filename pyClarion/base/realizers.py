"""Tools for defining construct behavior."""


__all__ = ["Realizer", "Construct", "Structure", "Updater"]


from pyClarion.base.symbols import ConstructType, Symbol, ConstructRef, feature
from pyClarion.base.components import (
    Emitter, Propagator, Updater, UpdaterC, UpdaterS, Cycle, Assets
)
from itertools import combinations, chain
from abc import abstractmethod
from types import MappingProxyType
from typing import (
    TypeVar, Union, Tuple, Dict, Callable, Hashable, Generic, Any, Optional, 
    Text, Iterator, Iterable, Mapping, ClassVar, List, cast, no_type_check
)
import logging
from contextvars import ContextVar


Dt = TypeVar('Dt') # type variable for inputs to emitters
PullFunc = Callable[[], Dt]
PullFuncs = Mapping[Symbol, Callable[[], Dt]]
Inputs = Mapping[Symbol, Any]

Rt = TypeVar('Rt', bound="Realizer") 
StructureItem = Tuple[Symbol, "Realizer"]

# Context variables for automating/simplifying agent construction. Helps track
# items to be added to structures. 
build_ctx: ContextVar[ConstructRef] = ContextVar("build_ctx")
build_list: ContextVar[List["Realizer"]] = ContextVar("build_list")

# Autocomplete only works properly when bound is str. Why? - Can
# Et = TypeVar("Et", bound="Emitter[It, Ot]") is more desirable and similar 
# for Pt & Ct below; but, this is not supported as of 2020-07-20. - Can
Et = TypeVar("Et", bound="Emitter")
Ut = TypeVar("Ut", bound="Updater")
class Realizer(Generic[Et]):
    """
    Base class for construct realizers.

    Provides a standard interface for creating, inspecting, modifying and 
    propagating information across construct networks. 

    Follows a pull-based message-passing pattern for activation propagation and 
    a blackboard pattern for updates to persistent data. 
    """

    _inputs: Dict[Symbol, Callable[[], Any]]
    _output: Optional[Any]
    _input_cache: Inputs
    _update_cache: Inputs

    def __init__(self, name: Symbol, emitter: Et, updater: Ut = None) -> None:
        """
        Initialize a new Realizer instance.
        
        :param name: Identifier for client construct.  
        :param emitter: Procedure for activation propagation. Expected to be of 
            type Emitter.
        :param updater: Procedure for updating persistent construct data.
        """

        self._validate_name(name)
        self._log_init(name)

        self._construct = name
        self._inputs = {}
        self._output = emitter.emit()
        self._input_cache = {}
        self._update_cache = {}

        self.emitter = emitter
        self.updater = updater

        self._update_add_queue()

    def __repr__(self) -> Text:

        return "<{}: {}>".format(self.__class__.__name__, str(self.construct))

    @property
    def construct(self) -> Symbol:
        """Symbol for client construct."""

        return self._construct

    @property 
    def inputs(self) -> Mapping[Symbol, PullFunc[Any]]:
        """Mapping from input constructs to pull funcs."""

        return MappingProxyType(self._inputs)

    @property
    def output(self) -> Any:
        """
        Current output of self.
        
        Deleteing this attribute will simply revert it to the default value set 
        by self.emitter.
        """

        return self._output

    @output.setter
    def output(self, output: Any) -> None:

        self._output = output

    @output.deleter
    def output(self) -> None:
        
        self._output = self.emitter.emit() # default/empty output

    def step(self) -> None:
        """Advance the simulation by one time step."""

        self._propagate()
        self._update()

    def accepts(self, source: Symbol) -> bool:
        """Return true iff self pulls information from source."""

        val = self.emitter.expects(source)
        if self.updater is not None:
            val |= self.updater.expects(source)

        return val

    def offer(self, construct: Symbol, callback: PullFunc[Any]) -> None:
        """
        Add link from construct to self if self accepts construct.
        
        :param construct: Symbol for target construct.
        :param callback: A callable that returns data representing the output 
            of construct. Typically this will be the `view()` method of a 
            Realizer instance.
        """

        if self.accepts(construct):
            self._log_watch(construct)            
            self._inputs[construct] = callback

    def drop(self, construct: Symbol) -> None:
        """Remove link from construct to self."""

        self._log_drop(construct)
        try:
            del self._inputs[construct]
        except KeyError:
            pass

    def clear_inputs(self) -> None:
        """Clear self.inputs."""

        for construct in self.inputs:
            self.drop(construct)

    def view(self) -> Any:
        """Return current output of self."""
        
        return self._output

    @abstractmethod
    def _propagate(self) -> None:
        """
        Propagate activations.

        :param kwds: Keyword arguments for emitter.
        """

        raise NotImplementedError()

    @abstractmethod
    def _update(self) -> None:
        """Update persistent data associated with self."""
        
        raise NotImplementedError()

    def _pull_input_data(self) -> None:

        items = self.inputs.items()
        data = {src: ask() for src, ask in items if self.emitter.expects(src)}
        self._input_cache = MappingProxyType(data)

    def _pull_update_data(self) -> None:

        if self.updater is not None:
            items = self.inputs.items()
            condition = self.updater.expects
            data = {src: ask() for src, ask in items if condition(src)}
            self._update_cache = MappingProxyType(data)

    def _update_add_queue(self) -> None:
        """If current context contains an add queue, add self to it."""

        try:
            lst = build_list.get()
        except LookupError:
            pass
        else:
            lst.append(self)

    def _log_init(self, construct) -> None:

        tname = type(self).__name__
        try:
            context = build_ctx.get()
        except LookupError:
            msg = "Initializing %s %s."
            logging.debug(msg, tname, construct)
        else:
            msg = "Initializing %s %s in %s."
            logging.debug(msg, tname, construct, context)

    def _log_watch(self, construct: Symbol) -> None:

        try:
            context = build_ctx.get()
        except LookupError:
            logging.debug("Connecting %s to %s.", construct, self.construct)
        else:
            msg = "Connecting %s to %s in %s."
            logging.debug(msg, construct, self.construct, context)

    def _log_drop(self, construct: Symbol) -> None:

        try:
            context = build_ctx.get()
        except LookupError:
            msg = "Disconnecting %s from %s."
            logging.debug(msg, construct, self.construct)
        else:
            msg = "Disconnecting %s from %s in %s."
            logging.debug(msg, construct, self.construct, context)

    @staticmethod
    def _validate_name(name) -> None:

        if not isinstance(name, Symbol):
            msg = "Agrument 'name' must be of type Symbol got '{}' instead."
            raise TypeError(msg.format(type(name).__name__))


Pt = TypeVar("Pt", bound="Propagator")
class Construct(Realizer[Pt]):
    """
    A basic construct.
    
    Responsible for defining the behaviour of lowest-level constructs such as 
    individual nodes, bottom level networks, top level rule databases, 
    subsystem output terminals, short term memory buffers and so on.
    """

    def __init__(
        self,
        name: Symbol,
        emitter: Pt,
        updater: UpdaterC[Pt] = None,
    ) -> None:
        """
        Initialize a new construct realizer.
        
        :param name: Identifier for client construct.  
        :param emitter: Procedure for activation propagation. Expected to be of 
            type Propagator.
        :param updater: Procedure for updating persistent construct data.
        """

        super().__init__(name=name, emitter=emitter, updater=updater)

    def _propagate(self) -> None:

        self._pull_input_data()
        self.output = self.emitter(self.construct, self._input_cache)

    def _update(self) -> None:

        self.emitter.update(self.construct, self._input_cache, self.output)
        self._pull_update_data()
        if self.updater is not None:
            updater = cast(UpdaterC[Pt], self.updater)
            updater(
                construct=self.construct, 
                propagator=self.emitter, 
                inputs=self._input_cache, 
                output=self.output, 
                update_data=self._update_cache
            )

        
# TODO: Make sure that structure outputs reflect their contents accurately even 
# on the first cycle.

Ct = TypeVar("Ct", bound="Cycle")
S = TypeVar("S", bound="Structure")
class Structure(Realizer[Ct]):
    """
    A composite construct.
    
    Defines behaviour of higher-level constructs, such as agents and 
    subsystems, which may contain other constructs. 
    """

    # NOTE: It would be nice to have structures automatically connect to 
    # elements that their members accept. My first past attempt at this failed 
    # miserably. Does not seem doable w/o allowing realizers to have knowledge 
    # of their parents. I don't really want to do that unless it is absolutely 
    # necessary. - Can

    _started: bool
    _dict: Dict[ConstructType, Dict[Symbol, Realizer]]
    _assets: Any

    def __init__(
        self, 
        name: Symbol, 
        emitter: Ct,
        assets: Any = None,
        updater: UpdaterS = None,
    ) -> None:
        """
        Initialize a new Structure instance.
        
        :param name: Identifier for client construct.  
        :param emitter: Procedure for activation propagation. Expected to be of 
            type Emitter.
        :param assets: Data structure storing persistent data shared among 
            members of self.
        :param updater: Procedure for updating persistent construct data.
        """

        super().__init__(name=name, emitter=emitter, updater=updater)
        
        self._started = False
        self._dict = {}
        self.assets = assets if assets is not None else Assets()

    def __contains__(self, key: ConstructRef) -> bool:

        try:
            self.__getitem__(key)
        except KeyError:
            return False
        return True

    def __iter__(self) -> Iterator[Symbol]:

        for construct in chain(*self._dict.values()):
            yield construct

    def __getitem__(self, key: ConstructRef) -> Any:

        if isinstance(key, tuple):
            if len(key) == 0:
                raise KeyError("Key sequence must be of length 1 at least.")
            elif len(key) == 1:
                return self[key[0]]
            else:
                # Catch & output more informative error here? - Can
                head = self[key[0]]
                return head[key[1:]] 
        else:
            return self._dict[key.ctype][key]

    # TODO: Recursive application needs testing. - Can
    def __delitem__(self, key: ConstructRef) -> None:

        if isinstance(key, tuple):
            if len(key) == 0:
                raise KeyError("Key sequence must be of length 1 at least.")
            elif len(key) == 1:
                del self[key[0]]
            else:
                # Catch & output more informative error here? - Can
                head = self[key[0]]
                del head[key[1:]] 
        else:
            self._log_del(key)
            self.drop(construct=key)
            del self._dict[key.ctype][key]

    def __enter__(self):

        logging.debug("Entering context %s.", self.construct)
        # This sets the context variable up to track objects to be added to 
        # self.
        parent = build_ctx.get(())
        self._build_ctx_token = build_ctx.set(parent + (self.construct,))
        self._build_list_token = build_list.set([])

    def __exit__(self, exc_type, exc_value, traceback):

        # Add any newly defined realizers to self and clean up the context.
        _, add_list = build_ctx.get(), build_list.get()
        for realizer in add_list:
            self.add(realizer)
        build_ctx.reset(self._build_ctx_token)
        build_list.reset(self._build_list_token)
        logging.debug("Exiting context %s.", self.construct)

    def start(self) -> None:

        self._update_output()
        for realizer in self.values():
            if isinstance(realizer, Structure):
                realizer.start()
        self._started = True

    def step(self) -> None:

        if not self._started:
            raise ValueError("Must call Structure.start() prior to stepping.")
        super().step()

    def add(self, *realizers: Realizer) -> None:
        """
        Add realizers to self and any associated links.
        
        Calling add directly when building an agent may be error-prone, not to 
        mention cumbersome. A better approach may be to try using self as a 
        context manager. 
        
        When self is used as a context manager, any construct initialized 
        within the body of a with statement having self as its context manager 
        will automatically be added to self upon exit from the context. Nested 
        use of with statements in this way (e.g. to add objects to subsystems 
        within an agent) is well-behaved.
        """

        for realizer in realizers:
            self._log_add(realizer.construct)
            ctype = realizer.construct.ctype
            d = self._dict.setdefault(ctype, {})
            d[realizer.construct] = realizer
            self.update_links(construct=realizer.construct)

    def remove(self, *constructs: Symbol) -> None:
        """Remove constructs from self and any associated links."""

        for construct in constructs:
            del self[construct]

    def clear(self):
        """Remove all constructs in self."""

        self.remove(*self.keys())

    def keys(self, ctype: ConstructType = None) -> Iterator[Symbol]:
        """
        Return iterator over all construct symbols in self.
        
        :param ctype: If provided, only constructs of a type that have a 
            non-empty intersection with ctype will be included.
        """

        for ct in self._dict:
            if ctype is None or bool(ct & ctype):
                for construct in self._dict[ct]:
                    yield construct

    def values(self, ctype: ConstructType = None) -> Iterator[Realizer]:
        """
        Return iterator over all construct realizers in self.
        
        :param ctype: If provided, only constructs of a type that have a 
            non-empty intersection with ctype will be included.
        """

        for ct in self._dict:
            if ctype is None or bool(ct & ctype):
                for realizer in self._dict[ct].values():
                    yield realizer

    def items(self, ctype: ConstructType = None) -> Iterator[StructureItem]:
        """
        Return iterator over all symbol, realizer pairs in self.
        
        :param ctype: If provided, only constructs of a type that have a 
            non-empty intersection with ctype will be included.
        """

        for ct in self._dict:
            if ctype is None or bool(ct & ctype):
                for construct, realizer in self._dict[ct].items():
                    yield construct, realizer

    def offer(self, construct: Symbol, callback: PullFunc) -> None:
        """
        Add links from construct to self and any accepting members.
        
        :param construct: Symbol for target construct.
        :param callback: A callable that returns data representing the output 
            of construct. Typically this will be the `view()` method of a 
            Realizer instance.
        """

        super().offer(construct, callback)  
        with self:
            for realizer in self.values():
                realizer.offer(construct, callback)

    def drop(self, construct: Symbol) -> None:
        """Remove links from construct to self and any accepting members."""

        super().drop(construct)
        for realizer in self.values():
            realizer.drop(construct)

    def clear_inputs(self) -> None:
        """Clear self.inputs and remove all associated links."""

        for construct in self.inputs:
            for realizer in self.values():
                realizer.drop(construct)
        super().clear_inputs()           

    def update_links(self, construct: Symbol) -> None:
        """Add any acceptable links associated with member construct."""

        target = self[construct]
        for realizer in self.values():
            if target.construct != realizer.construct:
                realizer.offer(target.construct, target.view)
                target.offer(realizer.construct, realizer.view)
        for c, callback in self.inputs.items():
            target.offer(c, callback)

    def clear_links(self) -> None:
        """Remove all links to, among, and within all members of self."""

        for realizer in self.values():
            realizer.clear_inputs()
            if isinstance(realizer, Structure):
                realizer.clear_links()

    def reweave(self) -> None:
        """Recompute all links to, among, and within members of self."""

        self.clear_links()
        for construct, realizer in self.items():
            if isinstance(realizer, Structure):
                realizer.reweave()
            self.update_links(construct)

    def clear_outputs(self) -> None:
        """Clear output of self and all members."""

        for realizer in self.values():
            if isinstance(realizer, Structure):
                realizer.clear_outputs()
            else:
                del realizer.output

        self._update_output()

    def _propagate(self) -> None:

        for ctype in self.emitter.sequence:
            for c in self.values(ctype=ctype):
                c._propagate()
        self._update_output()

    def _update(self) -> None:
        """
        Update persistent data in self and all members.
        
        First calls `self.updater`, then calls `realizer.update()` on members. 
        In otherwords, updates are applied in a top-down manner relative to
        construct containment.
        """

        self._pull_update_data()
        if self.updater is not None:
            updater = cast(UpdaterS, self.updater)
            updater(
                construct=self.construct,
                inputs=self._input_cache,
                output=self.output,
                update_data=self._update_cache
            )
        for realizer in self.values():
            realizer._update()

    def _update_output(self) -> None:

        ctype = self.emitter.output
        data = {sym: c.output for sym, c in self.items(ctype=ctype)}
        self.output = self.emitter.emit(data)

    def _log_del(self, construct):

        try:
            context = build_ctx.get()
        except LookupError:
            logging.debug("Removing %s from %s.", construct, self.construct)
        else:
            msg = "Removing %s from %s in %s."
            logging.debug(msg, construct, self.construct, context)

    def _log_add(self, construct):

        try:
            context = build_ctx.get()
        except LookupError:
            logging.debug("Adding %s to %s.", construct, self.construct)
        else:
            msg = "Adding %s to %s in %s." 
            logging.debug(msg, construct, self.construct, context)
