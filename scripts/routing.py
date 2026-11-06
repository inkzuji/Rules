"""服务按原客户端顺序执行；AI 对外只有一个完整规则文件。"""
from pathlib import Path

AI_THEMES = ['AI/' + name for name in ('OpenAI', 'Claude', 'Gemini', 'Copilot', 'Others')]
PROXY_ORDER = ['Google', 'YouTube', 'Netflix', 'Disney', 'Spotify', 'Streaming',
               'GitHub', 'Microsoft', 'Social', 'Dev', 'Cloudflare', 'Others']
SERVICE_NAMES = (['AI', 'Apple', 'Game'] + ['Proxy/' + name for name in PROXY_ORDER]
                 + ['Bilibili', 'Direct'])
THEME_NAMES = AI_THEMES + [name for name in SERVICE_NAMES if name != 'AI']
# 仅允许迁移本构建器已发布过的文件，未知文件仍阻断。
RETIRED_PATHS = ({name + '.list' for name in AI_THEMES}
                 | {'routing/' + name + '-domain.list' for name in THEME_NAMES})


def service_name(theme):
    return 'AI' if theme in AI_THEMES else theme


def service_paths(directory):
    return sorted(path for path in Path(directory).rglob('*.list')
                  if 'routing' not in path.relative_to(directory).parts)


def service_order(theme):
    return SERVICE_NAMES.index(service_name(theme))


def entry_order(entry):
    name = entry[0].removeprefix('domain-')
    for service in sorted(SERVICE_NAMES, key=len, reverse=True):
        aliases = (service.replace('/', '-'), service.split('/')[-1])
        if any(name == alias or name.startswith(alias + '-') for alias in aliases):
            return service_order(service)
    # 未知服务不能通过排序意外取得业务优先级。
    raise ValueError(f'未知路由服务: {entry[0]}')


def surge_references(entries):
    lines = ['# 合并到 [Rule]；按服务顺序执行，AI 完整规则优先。']
    base = 'https://raw.githubusercontent.com/inkzuji/Rules/main/surge/'
    lines.extend(f'RULE-SET,{base}{relative},{policy}' for _, relative, policy, *_ in entries)
    lines.append('FINAL,🐠 Final')
    return ('\n'.join(lines) + '\n').encode('utf-8')
