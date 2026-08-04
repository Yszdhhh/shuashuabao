import React, { useState, useEffect, useRef } from 'react';
import { Terminal, Copy, Trash2, ArrowDownCircle, Search, Check } from 'lucide-react';
import { LogItem } from '../types';

interface LogConsoleProps {
  logs: LogItem[];
  onClear: () => void;
}

export const LogConsole: React.FC<LogConsoleProps> = ({ logs, onClear }) => {
  const [filter, setFilter] = useState<string>('');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll) {
      endRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const filteredLogs = logs.filter((log) =>
    log.text.toLowerCase().includes(filter.toLowerCase())
  );

  const copyLogs = () => {
    const text = logs.map((l) => `[${l.time}] ${l.text}`).join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getLineClass = (type: string, text: string) => {
    if (type === 'error' || text.includes('中断') || text.includes('失败')) {
      return 'text-red-400 bg-red-500/5';
    }
    if (type === 'warn' || text.includes('超时') || text.includes('miss')) {
      return 'text-amber-300';
    }
    if (text.includes('phase ') || text.includes('锚点BOSS') || text.includes('查找龙珠')) {
      return 'text-cyan-300 font-semibold';
    }
    return 'text-slate-300';
  };

  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm flex flex-col h-[320px]">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 border-b border-[#243044] pb-2.5 mb-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-blue-400">
          <Terminal className="w-4 h-4 text-emerald-400" />
          <span>运行控制台日志 ({logs.length} 行)</span>
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          {/* 搜索框 */}
          <div className="relative flex-1 sm:w-48">
            <Search className="w-3.5 h-3.5 text-[#8b9bb4] absolute left-2 top-2" />
            <input
              type="text"
              placeholder="过滤日志..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-full bg-[#0b1220] border border-[#243044] rounded pl-7 pr-2 py-1 text-xs text-white placeholder-[#8b9bb4] focus:outline-none focus:border-blue-500"
            />
          </div>

          <button
            type="button"
            onClick={() => setAutoScroll(!autoScroll)}
            className={`p-1.5 rounded border text-xs flex items-center gap-1 transition-all ${
              autoScroll
                ? 'bg-blue-600/20 text-blue-300 border-blue-500/40'
                : 'bg-[#0b1220] text-[#8b9bb4] border-[#243044]'
            }`}
            title="自动滚动到最新"
          >
            <ArrowDownCircle className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">滚屏</span>
          </button>

          <button
            type="button"
            onClick={copyLogs}
            className="p-1.5 bg-[#0b1220] border border-[#243044] text-[#8b9bb4] hover:text-slate-200 rounded text-xs flex items-center gap-1"
            title="复制所有日志"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>

          <button
            type="button"
            onClick={onClear}
            className="p-1.5 bg-[#0b1220] border border-[#243044] text-[#8b9bb4] hover:text-red-400 rounded text-xs flex items-center gap-1"
            title="清空控制台"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* 日志列表 */}
      <div className="flex-1 bg-[#080d16] border border-[#243044] rounded-lg p-3 overflow-y-auto font-mono text-xs space-y-1 select-text">
        {filteredLogs.length === 0 ? (
          <div className="text-[#8b9bb4] italic text-center py-8">
            暂无日志输出。点击“开始游戏”开启控制台实时追踪。
          </div>
        ) : (
          filteredLogs.map((log) => (
            <div
              key={log.id}
              className={`leading-relaxed px-1 py-0.5 rounded flex items-start gap-2 hover:bg-[#151c2c]/40 ${getLineClass(
                log.type,
                log.text
              )}`}
            >
              <span className="text-[#8b9bb4] shrink-0 font-mono text-[11px]">
                [{log.time}]
              </span>
              <span className="break-all whitespace-pre-wrap">{log.text}</span>
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
};
