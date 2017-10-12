""" This module includes dataflow firetask tasks """

__author__ = 'Ivan Kondov'
__email__ = 'ivan.kondov@kit.edu'
__copyright__ = 'Copyright 2016, Karlsruhe Institute of Technology'

import sys
from fireworks import Firework
from fireworks.core.firework import FWAction, FireTaskBase
from fireworks.utilities.fw_serializers import load_object
# from past.builtins import basestring
if sys.version_info[0] > 2:
    basestring = str


class CommandLineTask(FireTaskBase):
    """
    A Firetask to execute external commands in a shell

    Required params:
        - command_spec (dict): a dictionary specification of the command
          (see below for details)

    Optional params:
        - inputs ([str]): list of labels, one for each input argument
        - outputs ([str]): list of labels, one for each output argument
        - chunk_number (int): the serial number of the firetask
          when it is part of a series generated by a ForeachTask

    command_spec = {
        'command': [str], # mandatory
        label_1: dict_1, # optional
        label_2: dict_2, # optional
        ...
    }
    The 'command' is a representation of the command as to be used with
    subprocess package. The optional keys label_1, label_2, etc. are
    the actual labels used in the inputs and outputs. The dictionaries dict_1,
    dict_2, etc. have the following schema:
    {
        'binding': {
            prefix: str or None,
            separator: str or None
        },
        'source': {
            'type': 'path' or 'data' or 'identifier'
                     or 'stdin' or 'stdout' or 'stderr' or None,
            'value': str or int or float
        },
        'target': {
            'type': 'path' or 'data' or 'identifier'
                     or 'stdin' or 'stdout' or 'stderr' or None,
            'value': str
        }
    }

    Remarks
    -------

    * If the 'type' in the 'source' field is 'data' the 'value' can be of
    types 'str', 'int' and 'float'.

    * When a *str* is found instead of *dict* for some 'source', for example
    'source': 'string', 'string' is replaced with spec['string'] which must be
    available and of the schema of the 'source'.

    * When a *str* is found instead of *dict* for some label, for example
    label: 'string', 'string' is replaced with spec['string'] which can be a
    dictionary with this schema or a list of such dictionaries.
    """

    _fw_name = 'CommandLineTask'
    required_params = ['command_spec']
    optional_params = ['inputs', 'outputs', 'chunk_number']

    def run_task(self, fw_spec):
        cmd_spec = self['command_spec']
        ilabels = self.get('inputs')
        olabels = self.get('outputs')
        if ilabels is None:
            ilabels = []
        else:
            assert isinstance(ilabels, list), '"inputs" must be a list'
        if olabels is None:
            olabels = []
        else:
            assert isinstance(olabels, list), '"outputs" must be a list'

        inputs = []
        outputs = []
        for ios, labels in zip([inputs, outputs], [ilabels, olabels]):
            # cmd_spec: {label: {{binding: {}}, {source: {}}, {target: {}}}}
            for l in labels:
                if isinstance(cmd_spec[l], basestring):
                    inp = []
                    for item in fw_spec[cmd_spec[l]]:
                        if 'source' in item:
                            inp.append(item)
                        else:
                            inp.append({'source': item})
                else:
                    inp = {}
                    for key in ['binding', 'source', 'target']:
                        if key in cmd_spec[l].keys():
                            item = cmd_spec[l][key]
                            if isinstance(item, basestring):
                                inp[key] = fw_spec[item]
                            elif isinstance(item, dict):
                                inp[key] = item
                            else:
                                raise ValueError
                ios.append(inp)
        command = cmd_spec['command']

        outlist = self.command_line_tool(command, inputs, outputs)

        if len(outlist) > 0:
            if self.get('chunk_number') is not None:
                mod_spec = []
                if len(olabels) > 1:
                    assert len(olabels) == len(outlist)
                    for ol, out in zip(olabels, outlist):
                        for item in out:
                            mod_spec.append({'_push': {ol: item}})
                else:
                    for out in outlist:
                        mod_spec.append({'_push': {olabels[0]: out}})
                return FWAction(mod_spec=mod_spec)
            else:
                output_dict = {}
                for ol, out in zip(olabels, outlist):
                    output_dict[ol] = out
                return FWAction(update_spec=output_dict)
        else:
            return FWAction()

    def command_line_tool(self, command, inputs=None, outputs=None):
        """
        This function composes and executes a command from provided
        specifications.

        Required parameters:
            - command ([str]): the command as to be passed to subprocess.Popen

        Optional parameters:
            - inputs ([dict, [dict]]): list of the specifications for inputs;
              multiple inputs may be passed in one list of dictionaries
            - outputs ([dict]): list of the specifications for outputs

        Returns:
            - list of target dictionaries for each output:
                'target': {
                    'type': 'path' or 'data' or 'identifier'
                             or 'stdin' or 'stdout' or 'stderr' or None
                    'value': str
                }
            If outputs is None then an empty list is returned.
        """
        import os
        import uuid
        from subprocess import Popen, PIPE
        from shutil import copyfile

        def set_binding(arg):
            argstr = ''
            if 'binding' in arg.keys():
                if 'prefix' in arg['binding'].keys():
                    argstr += arg['binding']['prefix']
                if 'separator' in arg['binding'].keys():
                    argstr += arg['binding']['separator']
            return argstr

        arglist = command
        stdin = None
        stdout = None
        stderr = PIPE
        stdininp = None
        if inputs is not None:
            for inp in inputs:
                argl = inp if isinstance(inp, list) else [inp]
                for arg in argl:
                    argstr = set_binding(arg)
                    assert 'source' in arg.keys(), 'input has no key "source"'
                    assert (arg['source']['type'] is not None
                            and arg['source']['value'] is not None)
                    if 'target' in arg.keys():
                        assert arg['target'] is not None
                        assert arg['target']['type'] == 'stdin'
                        if arg['source']['type'] == 'path':
                            stdin = open(arg['source']['value'], 'r')
                        elif arg['source']['type'] == 'data':
                            stdin = PIPE
                            stdininp = str(arg['source']['value']).encode()
                        else:
                            # filepad
                            raise NotImplementedError()
                    else:
                        if arg['source']['type'] == 'path':
                            argstr += arg['source']['value']
                        elif arg['source']['type'] == 'data':
                            argstr += str(arg['source']['value'])
                        else:
                            # filepad
                            raise NotImplementedError()
                    if len(argstr) > 0:
                        arglist.append(argstr)

        if outputs is not None:
            for arg in outputs:
                if isinstance(arg, list):
                    arg = arg[0]
                argstr = set_binding(arg)
                assert 'target' in arg.keys()
                assert arg['target'] is not None
                if arg['target']['type'] == 'path':
                    assert 'value' in arg['target']
                    assert len(arg['target']['value']) > 0
                    path = arg['target']['value']
                    if os.path.isdir(path):
                        path = os.path.join(path, str(uuid.uuid4()))
                        arg['target']['value'] = path
                    if 'source' in arg.keys():
                        assert arg['source'] is not None
                        assert 'type' in arg['source'].keys()
                        if arg['source']['type'] == 'stdout':
                            stdout = open(path, 'w')
                        elif arg['source']['type'] == 'stderr':
                            stderr = open(path, 'w')
                        elif arg['source']['type'] == 'path':
                            pass
                        else:
                            argstr += path
                    else:
                        argstr += path
                elif arg['target']['type'] == 'data':
                    stdout = PIPE
                else:
                    # filepad
                    raise NotImplementedError()
                if len(argstr) > 0:
                    arglist.append(argstr)

        p = Popen(arglist, stdin=stdin, stderr=stderr, stdout=stdout)
        res = p.communicate(input=stdininp)
        if p.returncode != 0:
            err = res[1] if len(res) > 1 else ''
            raise RuntimeError(err)

        retlist = []
        if outputs is not None:
            for output in outputs:
                if ('source' in output.keys()
                        and output['source']['type'] == 'path'):
                    copyfile(
                        output['source']['value'],
                        output['target']['value']
                    )
                if output['target']['type'] == 'data':
                    output['target']['value'] = res[0].decode().strip()
                retlist.append(output['target'])

        return retlist


class ForeachTask(FireTaskBase):
    """
    This firetask branches the workflow creating parallel fireworks
    using FWAction: one firework for each element or each chunk from the
    *split* list. Each firework in this generated list contains the Firetask
    specified in the *task* dictionary. If the number of chunks is specified
    the *split* list will be divided into this number of chunks and each
    chunk will be processed by one of the generated child Fireworks.

    Required params:
        - task (dict): a dictionary version of the firetask
        - split (str): a label of an input list; it must be available both in
          the *inputs* list of the specified task and in the Firework **spec**.

    Optional params:
        - number of chunks (int): if provided the *split* input list will be
          divided into this number of sublists and each will be processed by
          a separate child firework
    """
    _fw_name = 'ForeachTask'
    required_params = ['task', 'split']
    optional_params = ['number of chunks']

    def run_task(self, fw_spec):
        assert isinstance(self['split'], basestring), self['split']
        assert isinstance(fw_spec[self['split']], list)
        if isinstance(self['task']['inputs'], list):
            assert self['split'] in self['task']['inputs']
        else:
            assert self['split'] == self['task']['inputs']

        split_field = fw_spec[self['split']]
        lensplit = len(split_field)
        assert lensplit != 0, ('input to split is empty:', self['split'])

        nchunks = self.get('number of chunks')
        if not nchunks:
            nchunks = lensplit
        chunklen = lensplit // nchunks
        if lensplit % nchunks > 0:
            chunklen = chunklen + 1
        chunks = [split_field[i:i+chunklen] for i in range(0, lensplit, chunklen)]

        fireworks = []
        for index, chunk in enumerate(chunks):
            spec = fw_spec.copy()
            spec[self['split']] = chunk
            task = load_object(self['task'])
            task['chunk_number'] = index
            name = self._fw_name + ' ' + str(index)
            fireworks.append(Firework(task, spec=spec, name=name))
        return FWAction(detours=fireworks)


class PythonFunctionTask(FireTaskBase):
    """
    This firetask passes *inputs* to a specified python function and
    stores the *outputs* to the spec of the current firework and the
    next firework using FWAction.

    Required params:
        - function (str): a Python function to integrate

    Optional params:
        - inputs ([str]): a list of labels of inputs which must be available
          in the spec
        - outputs ([str]): a list of labels that will be used to store
          the function's outputs in the spec
        - chunk_number (int): a serial number of the Firetask within a
          group of Firetasks generated by a ForeachTask
    """
    _fw_name = 'PythonFunctionTask'
    required_params = ['function']
    optional_params = ['inputs', 'outputs', 'chunk_number']

    def run_task(self, fw_spec):
        node_input = self.get('inputs')
        node_output = self.get('outputs')

        inputs = []
        if isinstance(node_input, basestring):
            inputs.append(fw_spec[node_input])
        elif isinstance(node_input, list):
            for item in node_input:
                inputs.append(fw_spec[item])
        elif node_input is not None:
            raise TypeError('input must be a string or a list')

        prefix, suffix = self['function'].split('.', 2)
        func = getattr(__import__(prefix), suffix)
        outputs = func(*inputs)

        if node_output is None:
            return FWAction()

        if not isinstance(node_output, list):
            node_output = [node_output]

        if len(node_output) == 0:
            return FWAction()
        elif len(node_output) == 1:
            if self.get('chunk_number') is None:
                return FWAction(update_spec={node_output[0]: outputs})
            else:
                if isinstance(outputs, (list, tuple, set)):
                    mod_spec = [{'_push': {node_output[0]: i}} for i in outputs]
                else:
                    mod_spec = [{'_push': {node_output[0]: outputs}}]
                return FWAction(mod_spec=mod_spec)
        else:
            assert isinstance(outputs, (list, tuple, set))
            assert len(outputs) == len(node_output)
            return FWAction(update_spec=dict(zip(node_output, outputs)))


class ForeachPythonFunctionTask(FireTaskBase):
    """
    This firetask branches the workflow creating parallel fireworks
    using FWAction: one firework for each element or each chunk from the
    *split* list. It has the same purpose a the generic ForeahTask but it
    creates child fireworks only with the PythonFunctionTask.

    Required params:
        - function (str): a Python function to call in the PythonFunctionTask
        - inputs ([str]): a list of labels of inputs which must be available
          in the **spec**
        - split (str): a label of the input that will be split and must be
          in the *inputs* list

    Optional params:
        - outputs ([str]): a list of labels that will be used to store the
          outputs
        - number of chunks (int): if provided the *split* input list will be
          divided into this number of sublists and each will be processed by
          a separate child firework
    """
    _fw_name = 'ForeachPythonFunctionTask'
    required_params = ['function', 'split', 'inputs']
    optional_params = ['outputs', 'number of chunks']

    def run_task(self, fw_spec):
        split_input = self['split']
        node_input = self['inputs']
        if not isinstance(split_input, basestring):
            raise TypeError('the "split" argument must be a string')
        if not isinstance(fw_spec[split_input], list):
            raise TypeError('the "split" argument must point to a list')
        if isinstance(node_input, list):
            if split_input not in node_input:
                raise ValueError('the "split" argument must be in argument list')
        else:
            if split_input != node_input:
                raise ValueError('the "split" argument must be in argument list')

        split_field = fw_spec[split_input]
        lensplit = len(split_field)
        if lensplit < 1:
            print(self._fw_name, 'error: input to split is empty:', split_input)
            return FWAction(defuse_workflow=True)

        nchunks = self.get('number of chunks')
        if not nchunks:
            nchunks = lensplit
        chunklen = lensplit // nchunks
        if lensplit % nchunks > 0:
            chunklen = chunklen + 1
        chunks = [split_field[i:i+chunklen] for i in range(0, lensplit, chunklen)]

        fireworks = []
        for index, chunk in enumerate(chunks):
            spec = fw_spec.copy()
            spec[split_input] = chunk
            fireworks.append(
                Firework(
                    PythonFunctionTask(
                        function=self['function'],
                        inputs=node_input,
                        outputs=self.get('outputs'),
                        chunk_number=index
                    ),
                    spec=spec,
                    name=self._fw_name + ' ' + str(index)
                )
            )
        return FWAction(detours=fireworks)


class JoinDictTask(FireTaskBase):
    """
    This firetask combines specified spec fields into a new dictionary.
    """
    _fw_name = 'JoinDictTask'
    required_params = ['inputs', 'output']
    optional_params = ['rename']

    def run_task(self, fw_spec):

        if not isinstance(self['output'], basestring):
            raise TypeError('"output" must be a single string item')

        if self['output'] not in fw_spec.keys():
            output = {}
        elif isinstance(fw_spec[self['output']], dict):
            output = fw_spec[self['output']]
        else:
            raise TypeError('"output" exists but is not a dictionary')

        for item in self['inputs']:
            if self.get('rename') and item in self['rename']:
                output[self['rename'][item]] = fw_spec[item]
            else:
                output[item] = fw_spec[item]

        return FWAction(update_spec={self['output']: output})


class JoinListTask(FireTaskBase):
    """
    This firetask combines specified **spec*** fields into a new list.
    """
    _fw_name = 'JoinListTask'
    required_params = ['inputs', 'output']

    def run_task(self, fw_spec):

        if not isinstance(self['output'], basestring):
            raise TypeError('"output" must be a single string item')
        if self['output'] not in fw_spec.keys():
            output = []
        elif isinstance(fw_spec[self['output']], list):
            output = fw_spec[self['output']]
        else:
            raise TypeError('"output" exists but is not a list')

        for item in self['inputs']:
            output.append(fw_spec[item])

        return FWAction(update_spec={self['output']: output})


class ImportDataTask(FireTaskBase):
    """
    Update the spec with data from file in a nested dictionary at a position
    specified by a mapstring = maplist[0]/maplist[1]/...
    i.e. spec[maplist[0]][maplist[1]]... = data
    """

    _fw_name = 'ImportDataTask'
    required_params = ['filename', 'mapstring']
    optional_params = []

    def run_task(self, fw_spec):
        from functools import reduce
        import operator
        import json

        filename = self['filename']
        mapstring = self['mapstring']
        assert isinstance(filename, basestring)
        assert isinstance(mapstring, basestring)
        maplist = mapstring.split('/')

        with open(filename, 'r') as inp:
            data = json.load(inp)

        leaf = reduce(operator.getitem, maplist[:-1], fw_spec)
        if isinstance(data, dict):
            if maplist[-1] not in list(leaf.keys()):
                leaf[maplist[-1]] = data
            else:
                leaf[maplist[-1]].update(data)
        else:
            leaf[maplist[-1]] = data

        return FWAction(update_spec={maplist[0]: fw_spec[maplist[0]]})
