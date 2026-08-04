"""对齐原 GameScript.Jobs.LongzhuJob : AutoJob。"""

from __future__ import annotations

from gamescript.jobs.auto_job import AutoJob
from gamescript.loop_action import LoopAction


class LongzhuJob(AutoJob):
    def step(self) -> LoopAction:
        # 龙珠相关模板优先
        names = [
            "longzhu",
            "longzhu2",
            "closeLongzhu",
            "FindLongzhu",
        ]
        if self.find(names):
            self.click_match(names, "Longzhu")
            return LoopAction.Continue
        return super().step()
