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

""" Abstract syntax tree (AST) transformer to trace function calls.
"""
from __future__ import absolute_import

import ast
import sys
from .ast_transform import to_attribute, to_call, to_name, to_name_constant, \
    to_list, to_tuple

from traitlets import HasTraits, Any

# Does `ast.Starred` exist?
ast_has_starred = sys.version_info.major >= 3 and sys.version_info.minor >= 5


class ASTTracer(HasTraits):
    """ Trace function calls and variable gets and sets by AST rewriting.

    This class should be used with `ASTTraceTransformer`. It is very low-level
    and should be supplemented with additional logic to be useful. The `Tracer`
    class in this subpackage shows how to do this in an event-based way.
    """

    def trace_function(self, function, nargs):
        """ Called after function object (not function call!) is evaluated.
        """
        return self._unbox(self._trace_function(function, nargs))
    
    def trace_argument(self, arg_value, arg_name=None, nstars=0):
        """ Called after function argument is evaluated.
        """
        return self._unbox(self._trace_argument(arg_value, arg_name, nstars))

    def trace_return(self, return_value, multiple_values=False):
        """ Called after function returns.
        """
        return self._unbox(self._trace_return(return_value, multiple_values))
    
    def trace_access(self, name, value):
        """ Called after a variable is accessed.
        """
        return self._unbox(self._trace_access(name, value))
    
    def trace_assign(self, names, value):
        """ Called before a variable is assigned.
        """
        return self._unbox(self._trace_assign(names, value))
    
    def trace_delete(self, names):
        """ Called before a variable is deleted.
        """
        return self._trace_delete(names)
    
    def _trace_function(self, function, args):
        """ Called after function object is evaluated.
        
        May be reimplemented in subclass.
        """
        return function
    
    def _trace_argument(self, arg_value, arg_name=None, nstars=0):
        """ Called after function argument is evaluated.
        
        May be reimplemented in subclass.
        """
        return arg_value
    
    def _trace_return(self, return_value, multiple_values=False):
        """ Called after function returns.

        May be reimplemented in subclasss.
        """
        return return_value
    
    def _trace_access(self, name, value):
        """ Called after a variable is accessed.

        May be reimplemented in subclass.
        """
        return value
    
    def _trace_assign(self, names, value):
        """ Called before a variable is assigned.

        May be reimplemented in subclass.
        """
        return value
    
    def _trace_delete(self, names):
        """ Called before a variable is deleted.

        May be reimplemented in subclass.
        """
    
    def _unbox(self, x):
        """ Unbox a value, if it is boxed.
        """
        return x.value if isinstance(x, BoxedValue) else x


class ASTTraceTransformer(ast.NodeTransformer):
    """ Rewrite AST to trace function calls and variable gets and sets.
    """

    def __init__(self, tracer):
        super(ASTTraceTransformer, self).__init__()
        self.tracer = to_name(tracer)
        self._state = {} # Hack to pass state to immediate child node.
    
    def tracer_method(self, method, private=False):
        """ Make AST node for a method on the tracer.
        """
        if private:
            method = '_' + method
        return to_attribute(self.tracer, method)
    
    def visit(self, node):
        """ Reimplemented to clear state on visit.
        """
        self._state.clear()
        return super(ASTTraceTransformer, self).visit(node)
    
    def visit_with_state(self, node, **kwargs):
        """ Visit node, after setting state for this (non-generic) visit only.
        """
        self._state.clear()
        self._state.update(kwargs)
        return super(ASTTraceTransformer, self).visit(node)
    
    def visit_Call(self, call):
        """ Rewrite AST Call node with tracing.

        Replaces function and method calls, e.g.

            f(x,y,z=1)
        
        with wrapped calls, e.g.

            trace_return(trace_function(f)(
                trace_argument(x), trace_argument(y), z=trace_argument(1,'z')))
        
        The AST transformer allows boxed values (see `BoxedValue` type) to be
        passed through compositions of trace calls via the '_trace_*' variants
        of the `trace_*` methods. E.g., the `x` argument in the function call

            f(x=g())
        
        becomes

            ...(x=trace_argument(_trace_return(...), 'x'))
        """
        boxed = self._state.get('boxed', False)
        multiple_values = self._state.get('multiple_values', False)
        func = self.visit(call.func)

        # Visit positional and keyword arguments.
        args = [ self.visit_argument(arg) for arg in call.args ]
        keywords = [ ast.keyword(kw.arg, self.visit_argument(
                        kw.value, kw.arg, 2 if kw.arg is None else 0
                     )) for kw in call.keywords ]
        nargs = len(args) + len(keywords)

        # Handle *args and **kwargs in Python 3.4 and lower.
        starargs, kwargs = None, None
        if not ast_has_starred:
            if call.starargs is not None:
                starargs = self.visit_argument(call.starargs, nstars=1)
                nargs += 1
            if call.kwargs is not None:
                kwargs = self.visit_argument(call.kwargs, nstars=2)
                nargs += 1

        return to_call(
            self.tracer_method('trace_return', private=boxed), [
            to_call(
                to_call(self.tracer_method('trace_function'), [
                    func, ast.Num(nargs)
                ]),
                args, keywords, starargs, kwargs
            ),
            to_name_constant(multiple_values),
        ])
    
    def visit_argument(self, arg_value, arg_name=None, nstars=0):
        """ Rewrite AST node appearing as function argument.
        """
        # Unpack starred expression in Python 3.5+.
        starred = ast_has_starred and isinstance(arg_value, ast.Starred)
        if starred:
            arg_value = arg_value.value
            nstars = 1
        
        # Create new call.
        args = [ self.visit_with_state(arg_value, boxed=True) ]
        if arg_name:
            args += [ ast.Str(arg_name) ]
        keywords = []
        if nstars:
            keywords += [ ast.keyword('nstars', ast.Num(nstars)) ]
        call = to_call(self.tracer_method('trace_argument'), args, keywords)

        # Repack starred expression in Python 3.5+.
        if starred:
            call = ast.Starred(call, ast.Load())
        return call
    
    def visit_Name(self, name):
        """ Rewrite AST Name node with tracing.

        Replaces variable accesses, e.g. `x`, with wrapped accesses, e.g.

            trace_access('x', x)
        """
        if isinstance(name.ctx, ast.Load):
            boxed = self._state.get('boxed', False)
            return to_call(self.tracer_method('trace_access', private=boxed), [
                ast.Str(name.id),
                name,
            ])
        return name
    
    def visit_Assign(self, node):
        """ Rewrite AST Assign node with tracing.

        Replaces variable assignments, e.g.

            x = y = 1
        
        with wrapped assignments, e.g.

            x = y = trace_assign(['x','y'], 1)
        """
        targets_literal = to_list(map(self.target_to_literal, node.targets))

        # Is this a compound assignment, e.g. `x,y = ...` or, for our purposes,
        # even `z = x,y = ...`?
        targets = ast.literal_eval(targets_literal)
        multiple_values = any(not isinstance(t, str) for t in targets)

        node.value = to_call(self.tracer_method('trace_assign'), [
            targets_literal,
            self.visit_with_state(node.value,
                boxed=True, multiple_values=multiple_values),
        ])
        return node
    
    def target_to_literal(self, node):
        """ Convert assignment target to AST literal node.
        """
        if isinstance(node, ast.Name):
            return ast.Str(node.id)
        elif isinstance(node, ast.Tuple):
            return to_tuple(map(self.target_to_literal, node.elts))
        elif isinstance(target, ast.List):
            return to_list(map(self.target_to_literal, node.elts))
        else:
            raise TypeError("Unsupported assignment target %s" % node)
    
    def visit_Delete(self, node):
        """ Rewrite AST Delete node with tracing.

        Replaces variable deletions, e.g.

            del x, y
        
        with

            trace_delete(['x','y'])
            del x, y
        """
        self.generic_visit(node)
        names = [ n.id for n in node.targets if isinstance(n, ast.Name) ]
        names_node = to_list(ast.Str(name) for name in names)
        return [
            ast.Expr(to_call(self.tracer_method('trace_delete'), [names_node])),
            node,
        ]


class BoxedValue(HasTraits):
    """ A boxed value.

    Boxed values can be to pass extra data, not contained in the original
    program, between tracer callbacks. This is useful for connecting function
    arguments to the function call, for example.

    Note that the value in the box may have any type, not necessarily primitive.
    """
    value = Any()