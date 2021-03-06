# Copyright 2018 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import

from ipykernel.ipkernel import IPythonKernel
from networkx.readwrite import json_graph
from traitlets import Bool, Enum, Instance, Type, default

from ..core.annotator import Annotator
from ..core.flow_graph import flow_graph_to_graphml
from ..core.flow_graph_builder import FlowGraphBuilder
from ..core.graphml import write_graphml_str
from ..core.remote_annotation_db import RemoteAnnotationDB
from ..trace.tracer import Tracer
from .serialize import object_to_json
from .shell import FlowGraphIPythonShell
from .slots import get_slots


class FlowGraphIPythonKernel(IPythonKernel):
    """ IPython kernel with support for program analysis and object inspection.
    """
    
    # Whether to simplify the flow graph by removing some/all outputs.
    # See `flow_graph.flow_graph_to_graphml`.
    flow_graph_outputs = Enum(
        ['all', 'simplify', 'none'], default_value='simplify').tag(config=True)
    
    # Whether to store annotated slots of objects in the flow graph.
    # See `flow_graph_builder.FlowGraphBuilder`.
    flow_graph_slots = Bool(True).tag(config=True)
    
    # Annotator for objects and functions.
    annotator = Instance(Annotator)
    
    # `IPythonKernel` traits.
    shell_class = Type(FlowGraphIPythonShell)
    
    # Private traits.
    _builder = Instance(FlowGraphBuilder)
    _tracer = Instance(Tracer, args=())
    _trace_flag = Bool()

    # `FlowGraphIPythonKernel` interface
    
    def get_object(self, obj_id):
        """ Get a tracked object by ID.
        """
        return self._tracer.object_tracker.get_object(obj_id)
    
    def get_object_id(self, obj):
        """ Get the ID of a tracked object.
        """
        return self._tracer.object_tracker.get_id(obj)
    
    # `KernelBase` interface
    
    def do_execute(self, code, silent, *args, **kwargs):
        """ Reimplemented to perform tracing.
        """
        # Do execution, with tracing unless the execution request is `silent`.
        self._builder.reset()
        self._trace_flag = not silent
        reply_content = super(FlowGraphIPythonKernel, self).do_execute(
            code, silent, *args, **kwargs)
        
        # Add flow graph as a payload.
        if self._trace_flag and reply_content['status'] == 'ok':
            graph = self._builder.graph
            graphml = flow_graph_to_graphml(
                graph, outputs=self.flow_graph_outputs)
            data = write_graphml_str(graphml, prettyprint=False)
            payload = {
                'source': 'flow_graph',
                'mimetype': 'application/graphml+xml',
                'data': data,
            }
            reply_content['payload'].append(payload)
        
        return reply_content
    
    def inspect_request(self, stream, ident, parent):
        """ Reimplemented to handle inspect requests for annotated objects.
        """
        content = parent['content']
        if 'object_id' not in content:
            return super(FlowGraphIPythonKernel, self).inspect_request(
                stream, ident, parent)

        obj_id = content['object_id']
        obj = self.get_object(obj_id)
        if obj is None:
            reply_content = {
                'status': 'ok',
                'found': False,
                'data': {},
                'metadata': {},
            }
        else:
            inspect_data = get_slots(obj, content['slots'])
            reply_content = {
                'status': 'ok',
                'found': True,
                'data': {
                    'application/json': object_to_json(inspect_data),
                },
                'metadata': {},
            }
        
        msg = self.session.send(stream, 'inspect_reply',
                                reply_content, parent, ident)
        self.log.debug("%s", msg)
    
    # Trait initializers
    
    @default('annotator')
    def _annotator_default(self):
        # Inherit database config from kernel.
        db = RemoteAnnotationDB(parent=self)
        return Annotator(db=db)
    
    @default('_builder')
    def _builder_default(self):
        builder = FlowGraphBuilder(
            annotator=self.annotator,
            store_slots=self.flow_graph_slots,
        )

        def handler(changed):
            event = changed['new']
            if event:
                builder.push_event(event)
        self._tracer.observe(handler, 'event')
    
        return builder
