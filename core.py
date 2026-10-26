from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from io import BytesIO
import re, html, json, hashlib
from urllib.parse import urlparse, urljoin
from email.message import EmailMessage
from email.policy import SMTP
import pymupdf

CENTROS = [
('011.0005.1','ALMOXARIFADO',3),('011.0010.1','SUPRIMENTOS',2),
('011.0012.1','SEGURANÇA DO TRABALHO',6),('013.0001.1','INFRAPAV',33),
('020.0002.1','CONTABILIDADE',10),('020.0003.1','DIRETORIA',3),
('020.0004.1','FINANCEIRO',4),('020.0006.1','DP/RH',6),
('020.0007.1','SEGUROS',2),('020.0009.1','COMPLIANCE',1),
('020.0008.1','TI',6),('024.0001.1','JURIDICO',0),
('025.0001.1','COMERCIAL',5),('052.0020.1','USINA SOROCABA',4),
('060.0001.1','ADM MANUTENÇÃO',23)]
ASSUNTO = 'TI - Notas Fiscais Para Lançamento do Setor Fiscal - EC'

def dinheiro(v):
    return f'{Decimal(v):,.2f}'.replace(',','X').replace('.',',').replace('X','.')

def ratear(valor):
    total = Decimal(str(valor)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    if total <= 0: raise ValueError('O valor da NF deve ser positivo.')
    valores = [(total * n / 108).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) for _,_,n in CENTROS]
    # Ajuste explícito no maior centro para fechar o total em centavos.
    ajuste = total - sum(valores)
    valores[3] += ajuste
    return valores, ajuste

def ler_msg(data):
    import extract_msg
    from bs4 import BeautifulSoup
    with extract_msg.Message(data) as m:
        body = m.body or ''
        soup = BeautifulSoup(m.htmlBody or b'', 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            url = html.unescape(a['href'])
            if any(x in url for x in ['/download','autoatendimento_document_viewer/']):
                item = (a.get_text(' ',strip=True) or 'Documento',url)
                if item not in links: links.append(item)
        if not links:
            links = [('Documento',u) for u in re.findall(r'https://[^<>\r\n]+',body) if '/download' in u or 'autoatendimento_document_viewer/' in u]
        anexos = [(a.longFilename or a.shortFilename or 'anexo.pdf', a.data) for a in m.attachments if (a.longFilename or a.shortFilename or '').lower().endswith('.pdf')]
        return dict(assunto=m.subject or '', remetente=m.sender or '', corpo=body,links=links,anexos=anexos)

def baixar(url):
    import requests
    # Apenas os hosts observados no exemplo. Cada redirecionamento é validado.
    allowed = {'apihub.totvs.com.br','suporte.totvs.com','nfe.totvs.com.br'}
    for _ in range(6):
        p=urlparse(url)
        if p.scheme!='https' or p.hostname not in allowed or p.username or p.port not in (None,443):
            raise ValueError('Endereço fora dos hosts TOTVS previstos. Baixe o PDF pelo navegador e carregue abaixo.')
        with requests.get(url, timeout=(10,45),stream=True,allow_redirects=False) as r:
            if r.is_redirect:
                url=urljoin(url,r.headers['Location']);continue
            r.raise_for_status()
            chunks=[]; size=0
            for chunk in r.iter_content(65536):
                size+=len(chunk)
                if size>25*1024*1024: raise ValueError('Documento maior que 25 MB.')
                chunks.append(chunk)
            data=b''.join(chunks)
        if not data.lstrip().startswith(b'%PDF-'):
            raise ValueError('O portal retornou uma página, não um PDF. Abra o link no navegador, faça login se necessário e carregue o PDF.')
        with pymupdf.open(stream=data,filetype='pdf') as d:
            if d.needs_pass: raise ValueError('PDF protegido por senha.')
        return data
    raise ValueError('Excesso de redirecionamentos.')

def sugerir(nf, boleto):
    def texto(data):
        with pymupdf.open(stream=data,filetype='pdf') as d: return '\n'.join(p.get_text() for p in d)
    t=texto(nf); b=texto(boleto)
    def achar(p,s):
        m=re.search(p,s,re.I);return m.group(1) if m else ''
    # Leitor do DANFSe TOTVS apresentado. Layouts diferentes exigem conferência.
    num=achar(r'DATA E HORA DA NFS-e\s+(\d+)',t)
    emissao=achar(r'DATA E HORA DA NFS-e\s+\d+\s+(\d{2}/\d{2}/\d{4})',t)
    valor=achar(r'VALOR TOTAL DA OPERAÇÃO / SERVIÇO.*?R\$\s*([\d.,]+)',t.replace('\n',' '))
    venc=achar(r'Vencimento\s+(\d{2}/\d{2}/\d{2,4})',b)
    if len(venc)==8:venc=venc[:-2]+'20'+venc[-2:]
    vb=achar(r'Valor do Documento\s+([\d.,]+)',b)
    return dict(numero=num,emissao=emissao,valor=valor,vencimento=venc,valor_boleto=vb)

def valor_decimal(s):
    s=s.strip().replace('R$','').replace(' ','')
    if ',' in s:s=s.replace('.','').replace(',','.')
    return Decimal(s)

def gerar_pdf(nota,nf,boleto):
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    valores,ajuste=ratear(nota['valor'])
    bio=BytesIO();styles=getSampleStyleSheet()
    flow=[Paragraph('ELLENCO | RATEIO - TOTVS',styles['Title']),Spacer(1,18)]
    for line in [f"Matriz | Fornecedor: TOTVS S.A. | NF: {nota['numero']}",f"Emissão: {nota['emissao']} | Valor total: R$ {dinheiro(nota['valor'])}"]:
        flow.append(Paragraph(html.escape(line),styles['Normal']))
    flow.append(Spacer(1,18))
    rows=[['Centro de custo','Descrição','Usuários','Valor (R$)']]
    rows += [[c,n,str(q),dinheiro(v)] for (c,n,q),v in zip(CENTROS,valores)]
    rows.append(['','TOTAL','108',dinheiro(nota['valor'])])
    table=Table(rows,colWidths=[85,220,55,105],repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#4472c4')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.4,colors.grey),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),('ALIGN',(2,1),(-1,-1),'RIGHT'),('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#d9e2f3'))]))
    flow += [table,Spacer(1,18),Paragraph('Observações: '+html.escape(nota['observacoes']),styles['Normal']),Spacer(1,10),Paragraph('Base fixa: 108 usuários. Rateio proporcional sobre o valor total da NF.',styles['Normal'])]
    if ajuste:flow.append(Paragraph(f'Ajuste de arredondamento em INFRAPAV: R$ {dinheiro(ajuste)}.',styles['Normal']))
    flow += [Spacer(1,20),Paragraph('Elaboração: ____________________     Aprovação: ____________________',styles['Normal'])]
    SimpleDocTemplate(bio).build(flow)
    out=pymupdf.open()
    for data in [nf,boleto,bio.getvalue()]:
        with pymupdf.open(stream=data,filetype='pdf') as doc:out.insert_pdf(doc)
    result=out.tobytes();out.close();return result

def email_html(notas):
    heads=['Empresa','NF / Fatura','Emissão','Vencimento','Valor','Centro de Custo','Observações']
    s='<p>Fiscal, bom dia!</p><p>Gentileza prosseguir com o lançamento das notas fiscais:</p><table style="border-collapse:collapse;font-family:Arial;font-size:12px" border="1" cellpadding="6"><tr style="background:#4472c4"><th colspan="7">Construções</th></tr><tr style="background:#bdd7ee">'
    s+=''.join('<th>'+x+'</th>' for x in heads)+'</tr>'
    for n in notas:
        values=['TOTVS S/A',n['numero'],n['emissao'],n['vencimento'],'R$ '+dinheiro(n['valor']),'Rateio',n['observacoes']]
        s+='<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in values)+'</tr>'
    return s+'</table><p>Att,</p>'

def eml(notas):
    m=EmailMessage(policy=SMTP);m['To']='fiscal@ellenco.com.br';m['Cc']='ti@ellenco.com.br';m['Subject']=ASSUNTO;m['X-Unsent']='1'
    m.set_content('Notas fiscais TOTVS e rateios. Veja a tabela na versão HTML.');m.add_alternative(email_html(notas),subtype='html')
    for n in notas:m.add_attachment(n['pdf'],maintype='application',subtype='pdf',filename=f"NF_{n['numero']}_merged.pdf")
    return m.as_bytes()
