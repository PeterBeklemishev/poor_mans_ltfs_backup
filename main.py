import json
import logging
import os
from dataclasses import dataclass, field


@dataclass
class Node:
    name: str
    files: list[str] = field(default_factory=list)
    nested: list['Node'] = field(default_factory=list)

    def get_by_path(self, *path):
        logging.debug(f'{self}.get_by_path({path=})')
        if not path or path == [self.name]:
            return self
        next_node = next(
            (
                node
                for node in self.nested
                if node.name == path[0]
            ),
            None,
        )
        if not next_node:
            return None
        elif len(path) == 1:
            return next_node
        elif len(path) > 1:
            return next_node.get_by_path(*path[1:])

    def iter_nested(self, path: list[str] = None):
        if path is None:
            path = []
        yield path, self
        for nested_node in self.nested:
            yield from nested_node.iter_nested([*path, self.name])


def _cut_prefix(prefix, path):
    if not path.startswith(prefix):
        raise Exception(f'Prefix {prefix} does not match path {path}!')

    path = path[len(prefix):]
    if path.startswith(os.path.sep):
        path = path[len(os.path.sep):]
    return path


def json_file_path_walker(file_path):
    def inner(prefix):
        with open(file_path, 'rt', encoding='utf-8') as f:
            entries = json.load(f)
            for entry in entries:
                if not entry[0].startswith(prefix):
                    continue
                yield entry

    return inner


def get_tree(root_path: str, path_walker=os.walk):
    tree = Node(name=root_path)
    depth = 1
    for path, directories, files in path_walker(root_path):
        depth += 1
        if depth // 1000:
            logging.debug(f'{depth=}')
        logging.debug(('->', path, directories, files))
        path = _cut_prefix(root_path, path)
        if path:
            path_parts = path.split(os.path.sep)
        else:
            path_parts = []

        logging.debug(f'{path_parts=}')
        if path_parts:
            logging.debug(f'got {path_parts=}')
            node = tree.get_by_path(*path_parts)
        else:
            logging.debug(f'no {path_parts=}, node is root')
            node = tree

        logging.debug(f'got {node=}')

        if node is None:
            parent_node = tree.get_by_path(*path_parts[:-1])
            logging.debug(f'{parent_node=}')
            parent_node.nested.append(Node(
                name=path_parts[-1],
                files=files,
            ))
        else:
            node.files = files

    return tree


def _escape_space(path):
    if ' ' in path:
        return f'"{path}"'
    return path


def _make_copy_command(source: str, destination: str, is_folder: bool = False):
    folder_flags = [
        '--recursive',
    ]
    return [
        _escape_space('C:\Program Files\HPE\LTFS\ltfscopy.exe'),
        *(folder_flags if is_folder else []),
        '--preservetime',
        '--verbose',
        '-s',
        _escape_space(source),
        '-d',
        _escape_space(destination),
    ]


def get_diff_fix_commands(network_share_drive: str, ltfs_drive: str, skip_node_prefix: bool = True):
    source_tree = get_tree(network_share_drive)
    # FIXME: os.walk по ltfs закешировано в джсон для простоты разработки
    target_tree = get_tree(ltfs_drive, path_walker=json_file_path_walker('ltfs_backup_listdir.json'))
    commands = []
    copiing_paths = []
    for node_path, source_node in source_tree.iter_nested():
        nested_from_seen = False
        target_node_path = [*node_path, source_node.name]
        if skip_node_prefix:
            target_node_path = target_node_path[1:]

        for copiing_path in copiing_paths:
            if target_node_path[:len(copiing_path)] == copiing_path:
                nested_from_seen = True
                break
        if nested_from_seen:
            logging.info(f'path {target_node_path} already copiing')
            continue

        target_node = target_tree.get_by_path(*target_node_path)
        if not target_node:
            logging.info(f'path {target_node_path} does not exist')
            copiing_paths.append(target_node_path)
            commands.append(_make_copy_command(
                os.path.join(source_tree.name, *target_node_path),
                os.path.join(target_tree.name, *target_node_path),
                is_folder=True,
            ))
            continue
        if set(source_node.files).symmetric_difference(target_node.files) != set():
            only_in_source = set(source_node.files) - set(target_node.files)
            only_in_target = set(target_node.files) - set(source_node.files)
            logging.info(
                f'path {target_node_path}: {only_in_source or "no"} files only in source, {only_in_target or "no"} files only in target',
            )
            for file_name in only_in_source:
                commands.append(_make_copy_command(
                    os.path.join(source_tree.name, *target_node_path, file_name),
                    os.path.join(target_tree.name, *target_node_path),
                ))
            if only_in_target:
                logging.error(f'path {target_node_path}: files {only_in_target} exists only in target fs!')
    return commands


def main():
    logging.basicConfig(level=logging.INFO)
    commands = get_diff_fix_commands('Z:photos', 'I:files\\photos')
    print('Copy this commands to .bat file or execute manually:\n\n')
    print('\n'.join(map(lambda k: ' '.join(k), commands)))


if __name__ == '__main__':
    main()
