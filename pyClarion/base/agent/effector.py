import abc
from ..node import Chunk, ChunkSet, Node
from ..activation.packet import ActivationPacket

class Effector(abc.ABC):
    """Links chunks to actions.
    """
    
    _buffer : ChunkSet = set()

    @abc.abstractmethod
    def is_actionable(self, node_ : Node) -> bool:
        """Return True if input is actionable by self.
        """
        pass

    def get_actionable_chunks(
        self, input_map : ActivationPacket
    ) -> ChunkSet:
        """Return the set of actionable chunks in given input.
        """

        actionable_chunks = set()
        for node_ in input_map:
            if isinstance(node_, Chunk) and self.is_actionable(node_):
                actionable_chunks.add(node_)
        return actionable_chunks

    @abc.abstractmethod
    def fire(self, chunk : Chunk) -> None:
        """Execute actions associated with given actionable chunk.

        kwargs:
            chunk: A chunk selected for action execution.
        """
        pass

    def fire_buffered(self):
        """Fire all chunks in self.buffer, then clear the buffer. 
        """

        for chunk in self.buffer:
            self.fire(chunk)
        self.buffer.clear()

    @property
    def buffer(self) -> ChunkSet:
        """Stores actions selected for execution.
        """
        return self._buffer
    
    @buffer.setter
    def buffer(self, value : ChunkSet) -> None:
        """Stores a shallow copy of value for later execution.
        """
        self._buffer = value.copy()