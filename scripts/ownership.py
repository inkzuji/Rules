"""服务归属契约：专属子域优先，公司公共域和共享基础设施不能被 AI 来源吞并。"""
from dataclasses import dataclass
import ipaddress
from pathlib import Path

from rules import POLICIES


# 只使用有完整标签边界的根域/后缀；顺序不决定归属，最具体的契约优先。
# ai.studio 的自定义应用域见 https://ai.google.dev/gemini-api/docs/aistudio-deploying
# copilot-stg.com 的 www 端点为 Microsoft Copilot Auth；注册归属见
# https://rdap.cscglobal.com/dbs/rdap-api/v1/domain/copilot-stg.com
SERVICE_DOMAINS = {
    'AI/OpenAI': '''openai.com chatgpt.com oaistatic.com oaiusercontent.com sora.com
        chatgpt.livekit.cloud openai.com.cdn.cloudflare.net openai.azure.com
        openaiapi-site.azureedge.net openai-api.arkoselabs.com
        production-openaicom-storage.azureedge.net openaicomproductionae4b.blob.core.windows.net''',
    'AI/Claude': 'anthropic.com claude.ai claude.com claudeusercontent.com',
    'AI/Gemini': '''gemini.google.com bard.google.com aistudio.google.com makersuite.google.com
        generativelanguage.googleapis.com gemini.gstatic.com aisandbox-pa.googleapis.com
        gemini.google generativeai.google flow.google jules.google opal.google antigravity.google ai.studio
        aicode.googleapis.com aida.googleapis.com aiplatform.googleapis.com
        antigravity.googleapis.com antigravity-pa.googleapis.com proactivebackend-pa.googleapis.com
        cloudaicompanion.googleapis.com notebooklm.google.com notebooklm.google
        notebooklm.googleapis.com notebooklm-pa.googleapis.com notebook.google.com
        jules.google.com labs.google.com labs.google flow.google.com opal.google.com
        deepmind.com deepmind.google geminiweb-pa.clients.google.com
        geminiweb-pa.clients6.google.com alkalimakersuite-pa.clients6.google.com
        webchannel-alkalimakersuite-pa.clients6.google.com''',
    'AI/Copilot': '''githubcopilot.com githubcopilot.net copilot.microsoft.com
        sydney.bing.com copilot-proxy.githubusercontent.com
        copilot-telemetry.githubusercontent.com copilot-telemetry-service.githubusercontent.com
        copilotprodattachments.blob.core.windows.net githubnext.com copilot.cloud.microsoft copilot.com
        copilot-stg.com''',
    'Proxy/YouTube': '''youtube.com youtube-nocookie.com youtu.be ytimg.com googlevideo.com
        youtubei.googleapis.com youtube.googleapis.com youtubeembeddedplayer.googleapis.com
        withyoutube.com youtubeeducation.com youtubefanfest.com youtubegaming.com
        youtubekids.com youtubemobilesupport.com yt.be''',
    'Proxy/Google': '''google.com googleapis.com googleusercontent.com gstatic.com google
        gmail.com googlemail.com ggpht.com ggpht.cn 1e100.net doubleclick.net googlesyndication.com
        googleadservices.com googletagmanager.com googletagservices.com google-analytics.com
        googleoptimize.com blogger.com blogspot.com android.com appspot.com appengine.google.com
        gvt1.com gvt2.com gvt3.com recaptcha.net firebase.com firebaseio.com firebaseapp.com
        firebaseappcheck.googleapis.com chromium.org googlesource.com''',
    'Proxy/GitHub': '''github.com githubusercontent.com githubassets.com github.io
        githubstatus.com github.blog atom.io dependabot.com gh.io ghcr.io ghe.com git.io
        githubapp.com githubhackathon.com githubpreview.dev githubsupport.com githubuniverse.com
        myoctocat.com npm.community octocaptcha.com opensource.guide repo.new thegithubshop.com''',
    'Game': '''asobostudio.com beth.games bethesda.net bethesdagamestudios.com bethsoft.com
        callersbane.com doom.com elderscrolls.com flightsimulator.com forza.net forzamotorsport.net
        forzaracingchampionship.com forzarc.com gamepass.com minecraft-services.net minecraft.net
        minecraftservices.com minecraftshop.com mojang.com orithegame.com renovacionxboxlive.com
        tellmewhygame.com xbox xbox.co xbox.com xbox.eu xbox.org xboxab.com xboxgamepass.com
        xboxgamestudios.com xboxlive.cn xboxlive.com xboxone.co xboxone.com xboxone.eu
        xboxplayanywhere.com xboxservices.com xboxstudios.com xbx.lv
        bilibiligame.cn bilibiligame.co bilibiligame.net biligame.co biligame.com biligame.net
        steamcontent.com''',
    'Proxy/Microsoft': '''microsoft.com microsoftonline.com microsoft.net bing.com bing.net
        msn.com azure.com azure.net azureedge.net azurewebsites.net windows.net live.com
        office.com office365.com office.net onedrive.com visualstudio.com vscode.dev
        vsassets.io msedge.net windowsupdate.com microsoftapp.net microsoft-falcon.io
        appcenter.ms bingapis.com''',
    'Proxy/Cloudflare': '''cloudflare.com cloudflare.net cloudflare-dns.com cloudflareinsights.com
        cloudflarestorage.com workers.dev pages.dev''',
    'AI/Others': '''gateway.ai.cloudflare.com cursor.com cursor.sh cursor-cdn.com
        perplexity.ai perplexity.com pplx.ai huggingface.co huggingface.com hf.co
        x.ai grok.com grok.x.com midjourney.com suno.ai suno.com poe.com
        codeium.com windsurf.com ollama.com ollama.ai
        anythingllm.com arena.ai cerebras.ai character.ai chutes.ai civitai.com clipdrop.co
        codeiumdata.com coderabbit.ai cohere.ai cohere.com coze.com crewai.com cursorapi.com
        deepwiki.com deepwiki.org devin.ai dify.ai dreamgen.com duck.ai elevenlabs.com elevenlabs.io
        groq.com h2o.ai hf.space jasper.ai kimi.ai kiro.dev langchain.com leonardo.ai lmstudio.ai
        lovart.ai manus.im manuscdn.com marscode.com meta.ai minimax.io mistral.ai moonshot.ai
        novelai.net openart.ai openclaw.ai opencode.ai openrouter.ai poecdn.net qoder.com sider.ai
        trae.ai tripo3d.ai windsurf.build writesonic.com you.com grazie.ai grazie.aws.intellij.net
        codewhisperer.us-east-1.amazonaws.com q.us-east-1.amazonaws.com
        ppl-ai-file-upload.s3.amazonaws.com coderabbit.gallery.vsassets.io''',
    'Apple': 'apple.com icloud.com mzstatic.com apple-cloudkit.com',
    'Proxy/Netflix': 'netflix.com netflix.net nflxvideo.net nflximg.net nflxext.com nflxso.net',
    'Proxy/Disney': 'disneyplus.com disney.com dssott.com bamgrid.com hulu.com hbo.com max.com primevideo.com amazonvideo.com',
    'Proxy/Spotify': 'spotify.com scdn.co spotifycdn.com',
    'Proxy/Social': '''twitter.com x.com t.co twimg.com facebook.com fbcdn.net instagram.com
        cdninstagram.com telegram.org telegram.me t.me whatsapp.com whatsapp.net discord.com
        discord.gg discordapp.com discordapp.net reddit.com redd.it tiktok.com tiktokcdn.com''',
    'Proxy/Dev': '''algolia.net algolia.com auth0.com identrust.com intercom.io intercom.com
        intercomcdn.com launchdarkly.com livekit.cloud livekit.io segment.io segment.com
        sentry.io statsig.com statsigapi.net featuregates.org arkoselabs.com arkoselabs.net
        usefathom.com observeit.net envato-static.com envatousercontent.com
        px-cloud.net sheerid.com id.me withpersona.com datadoghq.com browser-intake-datadoghq.com
        hcaptcha.com clerk.com clerk.accounts.dev stytch.com workos.com
        docker.com docker.io npmjs.org npmjs.com pypi.org python.org jetbrains.com
        intellij.net cloudfront.net amazonaws.com''',
    'Proxy/Others': '''paypal.com paypalobjects.com paypal.me paypal.cn braintreegateway.com
        braintree-api.com braintreepayments.com getbraintree.com venmo.com xoom.com
        stripe.com stripe.network stripeassets.com stripecdn.com stripepayments.com
        chargebee.com checkout.com paddle.com paddle.net lemonsqueezy.com fastspring.com
        envato.com amazon.com auth.meta.com pypl.com pypl.info pypl.net pypl.tv''',
}
DOMAIN_OWNERS = {domain: theme for theme, domains in SERVICE_DOMAINS.items()
                 for domain in domains.split()}
HISTORICAL_NON_AI = frozenset(line.strip() for line in
    Path(__file__).with_name('non_ai_domains.txt').read_text(encoding='utf-8').splitlines()
    if line.strip() and not line.startswith('#'))

# Cloudflare 官方共享代理网段，核验于 2026-10-16：
# https://www.cloudflare.com/ips-v4 和 https://www.cloudflare.com/ips-v6
SHARED_CDN_NETWORKS = tuple(ipaddress.ip_network(value) for value in '''
173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 141.101.64.0/18
108.162.192.0/18 190.93.240.0/20 188.114.96.0/20 197.234.240.0/22 198.41.128.0/17
162.158.0.0/15 104.16.0.0/13 104.24.0.0/14 172.64.0.0/13 131.0.72.0/22
2400:cb00::/32 2606:4700::/32 2803:f800::/32 2405:b500::/32 2405:8100::/32
2a06:98c0::/29 2c0f:f248::/32
'''.split())
AI_PROCESSES = {'chatgpt', 'chatgpthelper', 'claude', 'gemini', 'perplexity',
                'midjourney', 'diffusionbee'}
UNSCOPED_KEYWORDS = {'google', 'gstatic', 'gmail', 'bing', 'github', 'microsoft',
                     'apple', 'cloudflare', 'paypal', 'stripe', 'amazon', 'youtube',
                     'youtubego', 'xbox360'}


@dataclass(frozen=True)
class Decision:
    theme: str | None
    reason: str


def domain_owner(domain):
    """返回最长后缀对应的服务；不按品牌词或任意子串猜测。"""
    labels = domain.lower().strip('.').split('.')
    for start in range(len(labels)):
        suffix = '.'.join(labels[start:])
        if suffix in DOMAIN_OWNERS:
            return DOMAIN_OWNERS[suffix]
        if suffix in HISTORICAL_NON_AI:
            return 'Proxy/Others'
    return None


def theme_policy(theme):
    prefix = theme.split('/')[0]
    return next(policy for policy, name in POLICIES.items() if name == prefix)


def decide(rule, policy, theme):
    typ, value, _ = rule
    fallback = theme or ('AI/Others' if policy == '🤖️AI' else
                         'Proxy/Others' if policy == '🚀节点选择' else POLICIES[policy])
    if typ in ('DOMAIN', 'DOMAIN-SUFFIX'):
        owner = domain_owner(value)
        return Decision(owner or fallback, '域名归属契约' if owner else '来源候选')
    if typ in ('IP-CIDR', 'IP-CIDR6'):
        network = ipaddress.ip_network(value)
        if any(network.version == shared.version and network.subnet_of(shared)
               for shared in SHARED_CDN_NETWORKS):
            return Decision('Proxy/Cloudflare', '共享 CDN 网段')
        if policy == '🤖️AI' and theme in (None, 'AI/Others'):
            return Decision('Proxy/Others', '聚合 IP 缺少服务专属证据')
    if typ == 'IP-ASN' and policy == '🤖️AI':
        return Decision('Proxy/Others', '整个 ASN 不能证明 AI 服务归属')
    if typ == 'DOMAIN-KEYWORD' and (policy == '🤖️AI' or value in UNSCOPED_KEYWORDS):
        return Decision(None, '宽泛关键词不能证明服务归属')
    if policy == '🤖️AI' and typ in ('USER-AGENT', 'URL-REGEX', 'DOMAIN-WILDCARD'):
        return Decision(None, '未经审核的宽匹配不能决定 AI 归属')
    if policy == '🤖️AI' and typ == 'PROCESS-NAME':
        process = value.lower()
        dedicated = process in AI_PROCESSES or any(
            f'/{name}.app/' in process for name in AI_PROCESSES)
        if not dedicated:
            return Decision(None, '通用进程不能决定 AI 归属')
    return Decision(fallback, '来源候选')
