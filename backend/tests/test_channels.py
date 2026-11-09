import json
import httpx
import pytest
from app import channels


@pytest.mark.parametrize('kind,data',[
    ('bark',{'code':200}),
    ('pushdeer',{'code':0,'content':{'result':[json.dumps({'success':1,'failure':0})]}}),
])
def test_provider_success_is_checked(kind,data,monkeypatch):
    observed=[]
    def handle(request):
        observed.append(request)
        return httpx.Response(200,json=data)
    real=httpx.Client
    monkeypatch.setattr(channels,'public_host',lambda _:None)
    monkeypatch.setattr(channels.httpx,'Client',lambda **kwargs:real(transport=httpx.MockTransport(handle),**kwargs))
    channels.deliver(kind,{'server':'https://push.example'},{'key':'test-only-secret'},'Title','Message')
    assert len(observed)==1
    assert 'test-only-secret' not in str(observed[0].url)
    assert observed[0].method=='POST'


@pytest.mark.parametrize('kind,data',[
    ('bark',{'code':400,'message':'provider error containing credentials'}),
    ('pushdeer',{'code':0,'content':{'result':[json.dumps({'success':0,'failure':1})]}}),
    ('pushdeer',{'code':0,'content':{'result':[]}}),
])
def test_http_200_is_not_always_delivery_success(kind,data,monkeypatch):
    real=httpx.Client
    monkeypatch.setattr(channels,'public_host',lambda _:None)
    monkeypatch.setattr(channels.httpx,'Client',lambda **kwargs:real(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=data)),**kwargs))
    with pytest.raises(channels.DeliveryError) as caught:
        channels.deliver(kind,{'server':'https://push.example'},{'key':'secret'},'Title','Message')
    assert 'credentials' not in str(caught.value)


def test_smtp_uses_starttls_and_checks_recipients(monkeypatch):
    calls=[]
    class SMTP:
        def __init__(self,*args,**kwargs): calls.append('connect')
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def starttls(self,**kwargs): calls.append('tls')
        def login(self,*args): calls.append('login')
        def send_message(self,message):
            calls.append('send')
            assert message['To']=='receiver@example.com'
            assert '中文' in message.get_content()
            return {}
    monkeypatch.setattr(channels,'public_host',lambda _:None)
    monkeypatch.setattr(channels.smtplib,'SMTP',SMTP)
    channels.deliver('smtp',{'host':'smtp.example.com','port':587,'tls':'starttls','username':'sender@example.com',
                           'sender':'sender@example.com','recipient':'receiver@example.com'}, {'password':'test'},'Title','中文')
    assert calls==['connect','tls','login','send']


def test_private_notification_address_rejected(system):
    with pytest.raises(channels.DeliveryError): channels.public_host('127.0.0.1')


def test_keyword_filter_and_ordered_extraction():
    config = channels.validate_channel('bark', {'server': 'https://api.day.app',
        'keywords': ['验证码', 'verify code'], 'content_mode': 'extract',
        'patterns': [r'不存在(\d+)', r'验证码[:：]\s*(\d+)', r'(\d+)']}, {'key': 'secret'})
    assert channels.matches_keywords(config, '您的验证码：123456')
    assert channels.matches_keywords(config, 'Your VERIFY CODE is 123456')
    assert not channels.matches_keywords(config, '普通消息')
    assert channels.delivery_content(config, '您的验证码：123456', 'legacy') == '123456'
    assert channels.delivery_content(config, '无可提取内容', 'legacy') is None
    assert channels.delivery_content({'content_mode': 'full'}, '原短信', 'legacy') == '原短信'
    assert channels.delivery_content({}, '原短信', 'legacy') == 'legacy'


def test_quicker_json_and_response(monkeypatch):
    observed = []
    def handle(request):
        observed.append(request)
        return httpx.Response(200, json={'isSuccess': True, 'successCount': 1})
    real = httpx.Client
    monkeypatch.setattr(channels, 'public_host', lambda _: None)
    monkeypatch.setattr(channels.httpx, 'Client', lambda **kwargs: real(transport=httpx.MockTransport(handle), **kwargs))
    config = {'toUser': 'someone@example.com', 'operation': 'PASTE', 'wait': True, 'maxWaitMs': 3000}
    channels.deliver('quicker', config, {'code': 'private-code'}, '标题', '123456')
    assert str(observed[0].url) == 'https://push.getquicker.cn/to/quicker'
    assert json.loads(observed[0].content)['data'] == '123456'
    assert json.loads(observed[0].content)['code'] == 'private-code'
    assert 'private-code' not in str(observed[0].url)
