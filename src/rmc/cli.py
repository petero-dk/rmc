"""CLI for converting rm files."""

import os
import sys
import io
import json
from pathlib import Path
from contextlib import contextmanager
from .exporters.svg import tree_to_svg
from .exporters.json import tree_to_json
import click
from rmscene import read_tree, read_blocks, write_blocks, simple_text_document


import logging


@click.command
@click.version_option()
@click.option('-v', '--verbose', count=True)
@click.option("-f", "--from", "from_", metavar="FORMAT", help="Format to convert from (default: guess from filename)")
@click.option("-t", "--to", metavar="FORMAT", help="Format to convert to (default: guess from filename)")
@click.option("-o", "--output", type=click.Path(), help="Output filename (default: write to standard out)")
@click.argument("input", nargs=-1, type=click.Path(exists=True))
def cli(verbose, from_, to, output, input):
    """Convert to/from reMarkable v6 files.

    Available FORMATs are: `rm` (reMarkable file), `markdown`, `svg`, `pdf`,
    `blocks`, `blocks-data`.

    Formats `blocks` and `blocks-data` dump the internal structure of the `rm`
    file, with and without detailed data values respectively.

    """

    if verbose >= 2:
        logging.basicConfig(level=logging.DEBUG)
    elif verbose >= 1:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    input = [Path(p) for p in input]
    if output is not None:
        output = Path(output)

    if from_ is None:
        if not input:
            raise click.UsageError("Must specify input filename or --from")
        from_ = guess_format(input[0])
    if to is None:
        if output is None:
            raise click.UsageError("Must specify --output or --to")
        to = guess_format(output)

    if from_ == "rm":
        with open_output(to, output) as fout:
            for fn in input:
                convert_rm(Path(fn), to, fout)
    else:
        raise click.UsageError("source format %s not implemented yet" % from_)


@contextmanager
def open_output(to, output):
    to_binary = to in ("pdf", "rm")
    if output is None:
        # Write to stdout
        if to_binary:
            with os.fdopen(sys.stdout.fileno(), "wb", closefd=False) as f:
                yield f
        else:
            yield sys.stdout
    else:
        with open(output, "w" + ("b" if to_binary else "t")) as f:
            yield f


def guess_format(p: Path):
    # XXX could be neater
    if p.suffix == ".rm":
        return "rm"
    if p.suffix == ".svg":
        return "svg"
    elif p.suffix == ".pdf":
        return "pdf"
    elif p.suffix == ".md" or p.suffix == ".markdown":
        return "markdown"
    else:
        return "blocks"


from rmscene import scene_items as si
def tree_structure(item):
    if isinstance(item, si.Group):
        return (
            item.node_id,
            (
                item.label.value,
                item.visible.value,
                (
                    item.anchor_id.value if item.anchor_id else None,
                    item.anchor_type.value if item.anchor_type else None,
                    item.anchor_threshold.value if item.anchor_threshold else None,
                    item.anchor_origin_x.value if item.anchor_origin_x else None,
                )
            ),
            [tree_structure(child) for child in item.children.values() if child],
        )
    else:
        return item


def convert_rm(filename: Path, to, fout):
    with open(filename, "rb") as f:
        if to == "blocks":
            json_blocks(f, fout)
        elif to == "blocks-data":
            json_blocks(f, fout, data=False)
        elif to == "json":
            tree = read_tree(f)
            tree_to_json(tree, fout)
        elif to == "svg":
            tree = read_tree(f)
            tree_to_svg(tree, fout)
        elif to == "tree":
            # Experimental dumping of tree structure
            json_tree(f, fout, data=True)
        elif to == "tree-data":
            # Experimental dumping of tree structure
            json_tree(f, fout, data=False)
        else:
            raise click.UsageError("Unknown format %s" % to)


def json_blocks(f, fout, data=True) -> None:
    depth = None if data else 1
    result = read_blocks(f)
    print("[", file=fout)
    for el, notlast in lookahead(result):
        json_string = json.dumps(el.__dict__, default=lambda o: getattr(o, '__dict__', None), indent=4)
        print(json_string, file=fout)
        if notlast:
            print(",", file=fout)
    print("]", file=fout)


def json_tree(f, fout, data=True) -> None:
    tree = read_tree(f)

    depth = None if data else 1
    tree_root = tree_structure(tree.root)
    tree_root_text = tree_structure(tree.root_text)

    tree_root_json = json.dumps(tree_root, default=lambda o: getattr(o, '__dict__', None), indent=4)
    print("[", file=fout)
    print(tree_root_json, file=fout)
    print(",", file=fout)
    tree_root_text_json = json.dumps(tree_root, default=lambda o: getattr(o, '__dict__', None), indent=4)
    print(tree_root_text_json, file=fout)
    print("]", file=fout)



def convert_text(text, fout):
    write_blocks(fout, simple_text_document(text))

def lookahead(iterable):
    """Pass through all values from the given iterable, augmented by the
    information if there are more values to come after the current one
    (True), or if it is the last value (False).
    """
    # Get an iterator and pull the first value.
    it = iter(iterable)
    try:
        last = next(it)
    except StopIteration:
        return
    # Run the iterator to exhaustion (starting from the second value).
    for val in it:
        # Report the *previous* value (more to come).
        yield last, True
        last = val
    # Report the last value.
    yield last, False

if __name__ == "__main__":
    cli()
