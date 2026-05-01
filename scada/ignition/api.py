

def get_production_report(url='https://productionmetrics.dolese.rocks/api/production-report/latest?site_id=101'):
    client = system.net.httpClient()
    response = client.get(url)
    body = response.getBody()
    body_text = body.tostring()
    data = system.util.jsonDecode(body_text)
    return data
