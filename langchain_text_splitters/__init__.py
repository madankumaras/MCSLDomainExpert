"""Compatibility shim for `langchain_text_splitters`."""
from __future__ import annotations

from importlib.machinery import PathFinder
from importlib.util import module_from_spec
from pathlib import Path
import sys


def _load_real_module():
    repo_root = Path(__file__).resolve().parents[1]
    search_path = [
        path
        for path in sys.path
        if path and Path(path).resolve() != repo_root
    ]
    spec = PathFinder.find_spec("langchain_text_splitters", search_path)
    if not spec or not spec.loader:
        return None
    current_module = sys.modules.get(__name__)
    module = module_from_spec(spec)
    try:
        sys.modules[__name__] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        if current_module is not None:
            sys.modules[__name__] = current_module
        else:
            sys.modules.pop(__name__, None)
        return None


_real_module = _load_real_module()
if _real_module is not None:
    globals().update(_real_module.__dict__)
else:
    class RecursiveCharacterTextSplitter:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.chunk_size = int(kwargs.get("chunk_size", 1000))
            self.chunk_overlap = int(kwargs.get("chunk_overlap", 0))
            self.separators = list(kwargs.get("separators", ["\n\n", "\n", " ", ""]))

        def _merge_splits(self, splits):
            docs = []
            current = ""
            for split in splits:
                if not split:
                    continue
                candidate = split if not current else current + split
                if len(candidate) <= self.chunk_size:
                    current = candidate
                    continue
                if current:
                    docs.append(current)
                current = split
                while len(current) > self.chunk_size:
                    docs.append(current[: self.chunk_size])
                    start = max(0, self.chunk_size - self.chunk_overlap)
                    current = current[start:]
            if current:
                docs.append(current)
            return docs

        def _split_text_recursive(self, text, separators):
            if len(text) <= self.chunk_size:
                return [text]
            if not separators:
                return [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

            separator = separators[0]
            if separator:
                pieces = text.split(separator)
                if len(pieces) == 1:
                    return self._split_text_recursive(text, separators[1:])
                splits = []
                for idx, piece in enumerate(pieces):
                    if idx < len(pieces) - 1:
                        splits.append(piece + separator)
                    else:
                        splits.append(piece)
                small_enough = all(len(part) <= self.chunk_size for part in splits if part)
                if small_enough:
                    return self._merge_splits(splits)
                nested = []
                for part in splits:
                    if len(part) <= self.chunk_size:
                        nested.append(part)
                    else:
                        nested.extend(self._split_text_recursive(part, separators[1:]))
                return self._merge_splits(nested)

            return self._merge_splits(
                [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]
            )

        def split_text(self, text):
            text = text or ""
            if not text:
                return []
            if self.chunk_size <= 0:
                return [text]
            return [chunk for chunk in self._split_text_recursive(text, self.separators) if chunk]

        def split_documents(self, documents):
            split_docs = []
            for doc in documents:
                page_content = getattr(doc, "page_content", "") or ""
                metadata = dict(getattr(doc, "metadata", {}) or {})
                chunks = self.split_text(page_content)
                if not chunks:
                    split_docs.append(doc)
                    continue
                doc_type = type(doc)
                for idx, chunk in enumerate(chunks):
                    chunk_meta = dict(metadata)
                    chunk_meta.setdefault("chunk_index", idx)
                    split_docs.append(doc_type(page_content=chunk, metadata=chunk_meta))
            return split_docs
