import hashlib
from datetime import datetime
import streamlit as st
from core import *

st.set_page_config(page_title='Ellenco | Fiscal TOTVS',page_icon='📄',layout='wide')
st.title('Ellenco | Notas fiscais TOTVS')
st.caption('Importe o e-mail, confira a nota e o boleto e prepare o envio ao Fiscal.')
st.session_state.setdefault('lote',[])
st.session_state.setdefault('pdfs',{})
st.session_state.setdefault('msgs',[])
with st.expander('1. Buscar no Outlook clássico do Windows'):
    st.write('Selecione a pasta em que chegam os e-mails destinados a ti@ellenco.com.br. A busca consulta os e-mails mais recentes, sem movê-los ou marcá-los como lidos.')
    limite=st.number_input('Quantidade de mensagens recentes a examinar',min_value=10,max_value=5000,value=300,step=10)
    if st.button('Selecionar pasta e buscar e-mails TOTVS'):
        try:
            from outlook import importar
            st.session_state.msgs=importar(int(limite));st.info(f'{len(st.session_state.msgs)} e-mail(s) encontrado(s).')
        except Exception as e:st.error('Não foi possível acessar o Outlook clássico: '+str(e))
msg=st.file_uploader('Ou carregue um e-mail salvo (.msg)',type=['msg'])
data=msg.getvalue() if msg else None
if st.session_state.msgs and not msg:
    idx=st.selectbox('E-mail encontrado',range(len(st.session_state.msgs)),format_func=lambda i:st.session_state.msgs[i][0])
    data=st.session_state.msgs[idx][1]
if data:
    try:
        mid=hashlib.sha256(data).hexdigest()
        if st.session_state.get('mid')!=mid:
            parsed=ler_msg(data);st.session_state.parsed=parsed;st.session_state.mid=mid
            st.session_state.pdfs={name:blob for name,blob in parsed['anexos']}
        parsed=st.session_state.parsed
        st.subheader(parsed['assunto'])
        st.caption(parsed['remetente'])
        with st.expander('Corpo do e-mail'):st.text(parsed['corpo'])
        for i,(label,url) in enumerate(parsed['links']):
            tipo='NF' if '/download' in url else ('Boleto' if '/3/' in url else 'Outro documento / RPS')
            st.write(f'{tipo}: {url}')
            if tipo in ['NF','Boleto'] and st.button(f'Baixar {tipo}',key=f'{mid}_{i}'):
                try:st.session_state.pdfs[f'{tipo}_{i}.pdf']=baixar(url);st.success('PDF carregado.')
                except Exception as e:st.error(str(e))
    except Exception as e:st.error('Não foi possível ler o arquivo: '+str(e))
st.subheader('2. Conferir NF e boleto')
for label,key in [('Nota fiscal em PDF','nf_manual'),('Boleto em PDF','boleto_manual')]:
    f=st.file_uploader(label,type=['pdf'],key=key)
    if f:st.session_state.pdfs[f'{label}: {f.name}']=f.getvalue()
names=list(st.session_state.pdfs)
if len(names)>=2:
    nf_name=st.selectbox('Arquivo da NF',names,index=0)
    bol_name=st.selectbox('Arquivo do boleto',names,index=1)
    nf=st.session_state.pdfs[nf_name];bol=st.session_state.pdfs[bol_name]
    key=hashlib.sha256(nf+bol).hexdigest()[:16]
    try:sug=sugerir(nf,bol)
    except Exception as e:st.error(str(e));st.stop()
    st.caption('Confira os campos nos documentos. A leitura automática foi adaptada ao DANFSe do exemplo; campos não reconhecidos ficam vazios.')
    with st.form('dados_'+key):
        num=st.text_input('Número da NF',sug['numero'])
        emi=st.text_input('Emissão (DD/MM/AAAA)',sug['emissao'])
        venc=st.text_input('Vencimento do boleto (DD/MM/AAAA)',sug['vencimento'])
        valor=st.text_input('Valor total da NF (base do rateio)',sug['valor'])
        vb=st.text_input('Valor do boleto',sug['valor_boleto'])
        obs=st.text_input('Observações para o Fiscal','RM - Suporte e Manutenção')
        ok=st.checkbox('Conferi fornecedor TOTVS, CNPJ da Ellenco, número da NF, valores, emissão e vencimento nos dois PDFs.')
        gerar=st.form_submit_button('Gerar PDF e incluir no lote')
    if gerar:
        try:
            if not ok:raise ValueError('Confira os dados e marque a confirmação.')
            if nf_name==bol_name or nf==bol:raise ValueError('Selecione arquivos diferentes para NF e boleto.')
            if not re.fullmatch(r'\d+',num):raise ValueError('Número de NF inválido.')
            num=str(int(num))
            for d in [emi,venc]:datetime.strptime(d,'%d/%m/%Y')
            if any(n['numero']==num for n in st.session_state.lote):raise ValueError('Essa NF já está no lote.')
            n=dict(numero=num,emissao=emi,vencimento=venc,valor=str(valor_decimal(valor)),valor_boleto=str(valor_decimal(vb)),observacoes=obs)
            if Decimal(n['valor_boleto'])<=0:raise ValueError('Valor de boleto inválido.')
            n['pdf']=gerar_pdf(n,nf,bol);st.session_state.lote.append(n)
            st.success('Incluída no lote. O PDF contém NF, boleto e rateio fixo, nessa ordem.')
        except Exception as e:st.error(str(e))
else:st.info('Carregue ou baixe a NF e o boleto, em PDFs separados.')
with st.expander('Rateio fixo TOTVS — 108 usuários'):
    st.table([{'Centro':c,'Descrição':n,'Usuários':q} for c,n,q in CENTROS])
st.subheader('3. Lote para o Fiscal')
notas=st.session_state.lote
if notas:
    st.markdown(email_html(notas),unsafe_allow_html=True)
    for n in list(notas):
        st.download_button('Baixar NF '+n['numero']+' + boleto + rateio',n['pdf'],file_name=f"NF_{n['numero']}_merged.pdf",mime='application/pdf')
        if st.button('Remover NF '+n['numero']):notas.remove(n);st.rerun()
    st.download_button('Baixar e-mail com todos os anexos (.eml)',eml(notas),file_name='Envio_Fiscal_TOTVS.eml',mime='message/rfc822')
    if st.button('Criar rascunho no Outlook clássico'):
        try:
            from outlook import rascunho
            rascunho(notas,email_html(notas),ASSUNTO);st.success('Rascunho aberto no Outlook. Confira a conta remetente e envie quando estiver pronto.')
        except Exception as e:st.error(str(e))
    st.caption('Nenhum envio automático. O lote fica na sessão atual; baixe os documentos antes de fechar. O controle de duplicidade abrange apenas este lote.')
