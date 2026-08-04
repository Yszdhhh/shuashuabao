import React, { useState } from 'react';
import { SlidersHorizontal, ChevronDown, ChevronUp, Clock, Cpu } from 'lucide-react';
import { AppSettings } from '../types';

interface AdvancedSettingsCardProps {
  settings: AppSettings;
  onChange: (key: keyof AppSettings, value: any) => void;
  disabled?: boolean;
}

export const AdvancedSettingsCard: React.FC<AdvancedSettingsCardProps> = ({
  settings,
  onChange,
  disabled = false,
}) => {
  const [isOpen, setIsOpen] = useState<boolean>(false);

  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="w-4 h-4 text-slate-400" />
          <span className="text-sm font-semibold text-slate-300">高级运维配置 (P2)</span>
          <span className="text-xs text-[#8b9bb4]">包含延迟、超时与清理间隔</span>
        </div>

        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="text-[#8b9bb4] hover:text-slate-200 p-1 rounded hover:bg-[#0b1220] flex items-center gap-1 text-xs"
        >
          <span>{isOpen ? '收起高级选项' : '展开高级选项'}</span>
          {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>

      {isOpen && (
        <div className="mt-4 pt-3 border-t border-[#243044] space-y-4 text-xs">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {/* 点击延迟 */}
            <div className="bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-[11px] text-[#8b9bb4] block mb-1">点击延迟(ms)</label>
              <input
                type="number"
                min={10}
                max={2000}
                value={settings.click_delay_ms}
                disabled={disabled}
                onChange={(e) => onChange('click_delay_ms', parseInt(e.target.value) || 120)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-white font-mono"
              />
            </div>

            {/* 循环间隔 */}
            <div className="bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-[11px] text-[#8b9bb4] block mb-1">循环休眠(ms)</label>
              <input
                type="number"
                min={50}
                max={5000}
                value={settings.loop_sleep_ms}
                disabled={disabled}
                onChange={(e) => onChange('loop_sleep_ms', parseInt(e.target.value) || 400)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-white font-mono"
              />
            </div>

            {/* 自动清理间隔 */}
            <div className="bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-[11px] text-[#8b9bb4] block mb-1">每 N 局清理内存</label>
              <input
                type="number"
                min={0}
                max={100}
                value={settings.auto_clean_interval}
                disabled={disabled}
                onChange={(e) => onChange('auto_clean_interval', parseInt(e.target.value) || 0)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-white font-mono"
              />
            </div>

            {/* 单局超时 */}
            <div className="bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-[11px] text-[#8b9bb4] block mb-1">单局超时(分钟)</label>
              <input
                type="number"
                min={1}
                max={120}
                value={settings.game_timeout}
                disabled={disabled}
                onChange={(e) => onChange('game_timeout', parseInt(e.target.value) || 15)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-white font-mono"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {/* 存活时间 */}
            <div className="bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-[11px] text-[#8b9bb4] block mb-1">Boss 存活上限(秒)</label>
              <input
                type="number"
                min={0}
                max={1000}
                value={settings.boss_live_time}
                disabled={disabled}
                onChange={(e) => onChange('boss_live_time', parseInt(e.target.value) || 200)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-white font-mono"
              />
            </div>

            {/* 存档时间 */}
            <div className="bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-[11px] text-[#8b9bb4] block mb-1">存档超时时间(秒)</label>
              <input
                type="number"
                min={0}
                max={1000}
                value={settings.archive_boss_time}
                disabled={disabled}
                onChange={(e) => onChange('archive_boss_time', parseInt(e.target.value) || 200)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-white font-mono"
              />
            </div>

            {/* 击杀 Boss 数量 */}
            <div className="bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-[11px] text-[#8b9bb4] block mb-1">目标击杀 Boss 数</label>
              <input
                type="number"
                min={0}
                max={9999}
                value={settings.kill_boss_num}
                disabled={disabled}
                onChange={(e) => onChange('kill_boss_num', parseInt(e.target.value) || 800)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-white font-mono"
              />
            </div>

            {/* 图集模板路径 */}
            <div className="bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-[11px] text-[#8b9bb4] block mb-1">模板资源目录</label>
              <input
                type="text"
                value={settings.images_dir}
                disabled={disabled}
                onChange={(e) => onChange('images_dir', e.target.value)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-white font-mono text-[11px]"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
