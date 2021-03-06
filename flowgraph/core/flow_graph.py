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

""" Create and manipulate flow graphs.

This module contains functions that create empty flow graphs and manipulate
existing flow graphs. To create a new flow graph by tracing Python code, see the
`flow_graph_builder` and `record` modules.

These graphs are sometimes called "concrete" or "raw" flow graphs to
distinguish them from other dataflow graphs in the Open Discovery system.
"""
from __future__ import absolute_import

import networkx as nx


def new_flow_graph():
    """ Create a new, empty flow graph.
    """
    # Warning: The names `__in__` and `__out__` are not a public interface.
    # Always access the input and output nodes through the `input_node` and
    # `output_node` graph attributes.
    input_node = '__in__'
    output_node = '__out__'
    
    graph = nx.MultiDiGraph()
    graph.add_nodes_from((input_node, output_node))
    graph.graph.update({
        'input_node': input_node,
        'output_node': output_node
    })
    return graph


def copy_flow_graph(source_graph, dest_graph):
    """ Copy all nodes and edges from source flow graph to destination flow graph.
    
    Note: The special input and output nodes of the source graph are ignored.
    """
    skip = (source_graph.graph['input_node'], source_graph.graph['output_node'])
    dest_graph.add_nodes_from(
        (node, data) for node, data in source_graph.nodes(data=True)
        if node not in skip)
    dest_graph.add_edges_from(
        edge for edge in source_graph.edges(data=True)
        if edge[0] not in skip and edge[1] not in skip)


def flow_graph_to_graphml(graph, outputs=None):
    """ Prepare a flow graph for serialization as GraphML.

    Returns another NetworkX graph suitable for serialization, not raw XML. To
    perform the serialization, call `graphml.write_graphml`.

    Since there are typically many outputs, the outputs can be pruned by
    setting the `outputs` option. Choose 'simplify to remove all outputs that
    are inputs to another call node, leaving only the "unused" outputs for the
    output ports. This convention does not always yield what would intuitively
    be regarded as the "outputs" of a particular program but one cannot expect
    too much from such a heuristic. Alternatively, choose 'none' to simply
    remove all the outputs.
    """
    # Bring the flow graph into conformance with the conventions for
    # representing wiring diagrams in GraphML.
    # TODO: Apply recursively to nested flow graphs.
    
    # The top-level graph must contain a single node, representing the outer box.
    graph = graph.copy()
    node = '__root__'
    outer = nx.MultiDiGraph()
    outer.add_node(node, graph=graph)
    
    # Every edge must have a source port and a target port. The only edges
    # that might be missing a source port (resp. target port) are the edges
    # from the input node (resp. to the output node) because these are
    # "unknown" inputs (resp. "last-modified" outputs). We make up port names
    # for these nodes.
    ports = {}
    input_node = graph.graph['input_node']
    output_node = graph.graph['output_node']
    data_keys = { 'annotation' }
    
    ninputs = 0
    input_map = {}
    for _, _, data in graph.out_edges(input_node, data=True):
        portname = input_map.get(data['id'])
        if not portname:
            ninputs += 1
            portname = 'in:' + str(ninputs)
            port_data = ports[portname] = { 'portkind': 'input' }
            port_data.update({k: data[k] for k in data_keys if k in data })
            input_map[data['id']] = portname
        data['sourceport'] = portname
    
    noutputs = 0
    for src, _, key, data in list(graph.in_edges(output_node, keys=True, data=True)):
        if (outputs == 'none' or
            (outputs == 'simplify' and _ncopies(graph, src, data['id']) > 0)):
            graph.remove_edge(src, output_node, key=key)
        else:
            noutputs += 1
            portname = 'out:' + str(noutputs)
            data['targetport'] = portname
            port_data = ports[portname] = { 'portkind': 'output' }
            port_data.update({k: data[k] for k in data_keys if k in data })
    
    outer.nodes[node]['ports'] = ports
    return outer

def _ncopies(graph, node, obj_id):
    """ Number of copies an object output by a node.
    
    (The count excludes the special output node.)
    """
    output_node = graph.graph['output_node']
    return sum(data.get('id') == obj_id
               for _, tgt, data in graph.out_edges(node, data=True)
               if tgt != output_node)

def flow_graph_from_graphml(outer):
    """ Returns a flow graph from deserialized GraphML.
    
    Expects a NetworkX graph, not raw XML.
    To deserialize GraphML, call `graphml.read_grapml`.
    """
    # Undo the transformations performed by `flow_graph_to_graphml`.
    assert len(outer) == 1
    node = list(outer.nodes)[0]
    graph = outer.nodes[node]['graph']

    input_node = graph.graph['input_node']
    output_node = graph.graph['output_node']
    for _, _, data in graph.out_edges(input_node, data=True):
        del data['sourceport']
    for _, _, data in graph.in_edges(output_node, data=True):
        del data['targetport']
    
    return graph


def flatten(graph, copy=True):
    """ Recursively flatten an object flow graph.
    
    All nested graphs are lifted to the root graph. This means that only 
    "atomic" (not traced) function calls will be preserved.
    """
    if copy:
        graph = graph.copy()
    input_node = graph.graph['input_node']
    output_node = graph.graph['output_node']
    
    for node in list(graph.nodes):
        subgraph = graph.nodes[node].get('graph', None)
        if not subgraph:
            continue
        subgraph = flatten(subgraph, copy=False)
        sub_input_node = subgraph.graph['input_node']
        sub_output_node = subgraph.graph['output_node']
        
        # First, add all nodes and edges from the subgraph.
        copy_flow_graph(subgraph, graph)
        
        # Re-wire the input objects of the subgraph.
        for _, tgt, data in subgraph.out_edges(sub_input_node, data=True):
            obj_id, tgt_port = data['id'], data['targetport']
            
            # Try to find an incoming edge in the parent graph carrying the
            # above object. There could be multiple edges carrying the object
            # (if the same object is passed to multiple arguments) but we need
            # only consider one because they should all have the same source.
            for src, _, data in graph.in_edges(node, data=True):
                if data['id'] == obj_id:
                    data.pop('targetport', None)
                    graph.add_edge(src, tgt, targetport=tgt_port, **data)
                    break
            # If that fails, add a new input object to the parent graph.
            else:
                graph.add_edge(input_node, tgt, **data)
        
        # Re-wire the output objects of the subgraph.
        for src, _, data in subgraph.in_edges(sub_output_node, data=True):
            obj_id, src_port = data['id'], data['sourceport']
            
            # Find outgoing edges in the parent graph carrying the above object.
            # If there are none, forget about the output: it cannot be a return
            # value or a mutated argument, hence is lost to the outer scope.
            for _, tgt, data in graph.out_edges(node, data=True):
                if data['id'] == obj_id:
                    data.pop('sourceport', None)
                    graph.add_edge(src, tgt, sourceport=src_port, **data)
        
        # Finally, remove the original node (and its edges).
        graph.remove_node(node)
    
    return graph


def join(first, second, copy=True):
    """ Join two object flow graphs that have been captured sequentially.
    """
    # Start with the first graph.
    graph = first.copy() if copy else first
    
    # Build output table. See `FlowGraphBuilder` for motivation.
    input_node = graph.graph['input_node']
    output_node = graph.graph['output_node']
    output_table = { data['id']: (src, key) for src, _, key, data
                     in graph.in_edges(output_node, keys=True, data=True) }
    
    # Add all nodes and edges from the second graph.
    copy_flow_graph(second, graph)

    # Add inputs from the second graph.
    for _, tgt, data in second.out_edges(second.graph['input_node'], data=True):
        # If there is a corresponding output of the first graph, use it.
        if data['id'] in output_table:
            src, key = output_table[data['id']]
            src_port = graph.edges[src,output_node,key]['sourceport']
            graph.add_edge(src, tgt, sourceport=src_port, **data)
        # Otherwise, add the input to the first graph.
        else:
            graph.add_edge(input_node, tgt, **data)
    
    # Add outputs from the second graph, overwriting outputs of the first graph
    # if there is a conflict.
    for src, _, data in second.in_edges(second.graph['output_node'], data=True):
        if data['id'] in output_table:
            old, key = output_table[data['id']]
            graph.remove_edge(old, output_node, key=key)
        graph.add_edge(src, output_node, **data)
        
    return graph
