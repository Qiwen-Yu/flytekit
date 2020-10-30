from __future__ import annotations
import typing
from typing import Tuple, Union, Optional

from flytekit.annotated.context_manager import ExecutionState, FlyteContext, BranchEvalMode
from flytekit.annotated.promise import ComparisonExpression, ConjunctionExpression, Promise


class ConditionalSection(object):
    def __init__(self):
        self._cases: typing.List[Case] = []
        self._selected_case = None
        self._last_case = False
        self._condition = None

        ctx = FlyteContext.current_context()
        if ctx.execution_state and ctx.execution_state.branch_eval_mode is not None:
            raise NotImplementedError("Nested branches are not yet supported")
        ctx = FlyteContext.current_context()
        if ctx.execution_state and ctx.execution_state.mode == ExecutionState.Mode.LOCAL_WORKFLOW_EXECUTION:
            """
            In case of local workflow execution we should ensure a conditional section
            is created so that skipped branches result in tasks not being executed
            """
            ctx.execution_state.enter_conditional_section()

    def set_condition(self, c: Condition):
        self._condition = c

    def start_branch(self, c: Case, last_case: bool = False) -> Case:
        self._last_case = last_case
        self._cases.append(c)
        ctx = FlyteContext.current_context()
        if ctx.execution_state and ctx.execution_state.mode == ExecutionState.Mode.LOCAL_WORKFLOW_EXECUTION:
            # This is a short-circuit for the case when the branch was taken
            # We already have a candidate case selected
            if self._selected_case is None:
                if c.expr is None or c.expr.eval():
                    ctx = FlyteContext.current_context().execution_state
                    ctx.take_branch()
                    self._selected_case = self._cases[-1]
        return self._cases[-1]

    def end_branch(self) -> Union[Condition, Promise]:
        ctx = FlyteContext.current_context()
        if ctx.execution_state:
            ctx.execution_state.branch_complete()
            if self._last_case:
                ctx.execution_state.exit_conditional_section()
            if self._last_case:
                if ctx.execution_state.mode == ExecutionState.Mode.LOCAL_WORKFLOW_EXECUTION:
                    if self._selected_case.output_promise is None and self._selected_case.err is None:
                        raise AssertionError("Bad conditional statements, did not resolve in a promise")
                    elif self._selected_case.output_promise is not None:
                        return self._selected_case.output_promise
                    raise ValueError(self._selected_case.err)
                else:
                    return self._cases[-1].output_promise
        return self._condition

    @property
    def cases(self) -> typing.List[Case]:
        return self._cases


class Case(object):
    def __init__(self, cs: ConditionalSection, expr: Optional[Union[ComparisonExpression, ConjunctionExpression]]):
        self._cs = cs
        self._expr = expr
        self._output_promise = None
        self._err = None

    @property
    def expr(self) -> Optional[Union[ComparisonExpression, ConjunctionExpression]]:
        return self._expr

    @property
    def output_promise(self) -> Optional[Promise]:
        return self._output_promise

    @property
    def err(self) -> Optional[str]:
        return self._err

    # TODO this is complicated. We do not want this to run
    def then(self, p: Union[Promise, Tuple[Promise]]) -> Union[Condition, Promise]:
        self._output_promise = p
        # We can always mark branch as completed
        return self._cs.end_branch()

    def fail(self, err: str) -> Promise:
        self._err = err
        return self._cs.end_branch()


class Condition(object):
    def __init__(self, cs: ConditionalSection):
        self._cs = cs

    def _if(self, expr: Union[ComparisonExpression, ConjunctionExpression]) -> Case:
        return self._cs.start_branch(Case(cs=self._cs, expr=expr))

    def elif_(self, expr: Union[ComparisonExpression, ConjunctionExpression]) -> Case:
        return self._cs.start_branch(Case(cs=self._cs, expr=expr))

    def else_(self) -> Case:
        return self._cs.start_branch(Case(cs=self._cs, expr=None), last_case=True)
