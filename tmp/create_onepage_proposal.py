from pathlib import Path
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'proposal'
OUT.mkdir(parents=True, exist_ok=True)
doc = Document()
for st in doc.styles:
    for border in list(st.element.iter(qn('w:pBdr'))):
        border.getparent().remove(border)
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.top_margin, sec.bottom_margin = Cm(1.65), Cm(1.65)
sec.left_margin, sec.right_margin = Cm(1.85), Cm(1.85)

for st in doc.styles:
    if st.type not in (1, 2):
        continue
    st.font.name = 'Microsoft YaHei'
    fonts = st.element.get_or_add_rPr().rFonts
    for attr in list(fonts.attrib):
        del fonts.attrib[attr]
    for attr in ['ascii', 'hAnsi', 'eastAsia', 'cs']:
        fonts.set(qn('w:' + attr), 'Microsoft YaHei')
    st.font.color.rgb = RGBColor(0, 0, 0)
normal = doc.styles['Normal']
normal.font.size = Pt(10.5)
normal.paragraph_format.line_spacing = Pt(15)
normal.paragraph_format.space_after = Pt(4)
title = doc.styles['Title']
title.font.size = Pt(20)
title.font.bold = True
title.paragraph_format.space_after = Pt(3)
head = doc.styles['Heading 1']
head.font.size = Pt(11.5)
head.font.bold = True
head.paragraph_format.space_before = Pt(8)
head.paragraph_format.space_after = Pt(4)

doc.add_paragraph('颔语 Gesture Bridge 一页方案说明', 'Title')
p = doc.add_paragraph('面向语言表达困难人群的手势辅助表达设备')
p.paragraph_format.space_after = Pt(8)

doc.add_paragraph('项目定位', 'Heading 1')
doc.add_paragraph('通过摄像头识别使用者的手势，将其转换为预先确认的生活表达，再由喇叭说出。使用者在控制面板通过图卡选意，家人可在面板填写句子协助建库；绑定后固定复用。例如，将张掌绑定为“我想喝水”，识别后经使用者确认再播报。')

doc.add_paragraph('目标人群与核心问题', 'Heading 1')
for label, text in [
    ('首发人群', '行动受限且难以通过语言表达需求的人群，例如渐冻症、高位截瘫、重度卒中患者。首版需使用者仍能稳定完成可识别的手势。'),
    ('延伸场景', '失语症、构音障碍、特教儿童，以及 ICU 术后等暂时无法正常发声的沟通场景。'),
    ('核心痛点', '传统沟通常依赖照护者猜测、代为表达或复杂辅助设备，沟通效率低且容易误解，使用者难以自主、及时地表达个性化需求。'),
]:
    p = doc.add_paragraph()
    p.add_run(label + '：').bold = True
    p.add_run(text)

doc.add_paragraph('工作流一  建立和修改个人词典', 'Heading 1')
p = doc.add_paragraph('选择含义 → 核对原句 → 录入手势 → 确认绑定 → 保存并试用')
p.runs[0].bold = True
doc.add_paragraph('在控制面板的“手势建库”页面，使用者可通过图卡选择含义，家人可点击“照护者填写”，输入想表达的完整句子。选定后录入三次手势，检查一致性及绑定冲突；使用者确认后保存，再试做验证。修改时先展示原绑定，重新核对后保存。家人协助填写不代替使用者本人确认。语音协助建库待接入。')

doc.add_paragraph('工作流二  识别手势并表达', 'Heading 1')
p = doc.add_paragraph('采集画面 → 识别手势 → 稳定保持 → 匹配词典 → 确认或取消 → 原句播报')
p.runs[0].bold = True
doc.add_paragraph('设备上电后自动识别，使用者将完整单手放入画面并保持手势。状态机生成一次有效动作事件，查询个人词典并展示候选句。使用者通过新的独立操作确认或取消；确认后播放已保存原句。持续保持同一手势不重复触发，画面失效或候选超时则清空待处理输入。')

doc.add_paragraph('技术实现路径', 'Heading 1')
table = doc.add_table(rows=1, cols=2)
table.autofit = False
table.columns[0].width, table.columns[1].width = Cm(2.35), Cm(14.95)
for c, t in zip(table.rows[0].cells, ['模块', '实现方式']):
    c.text = t
rows = [
 ('硬件采集', 'LJWB03 开发板、BF3901 SPI 摄像头、麦克风、喇叭与 RGB 灯板。'),
 ('板端识别', '图像转换 → 手部检测 → 128×128 手势分类；ESP-DL 当前目标为张掌和 V 字。'),
 ('动作判断', '结合置信度、连续观察、保持时间和释放去重，生成有效手势完成事件。'),
 ('词典管理', 'H5 控制面板提供图卡、照护者文字填写及演示绑定；设备词典同步待接入。'),
 ('语音与输出', '沿用官方联网语音链路接入配置理解；固定句预生成音频并缓存，确认后本地播放。'),
]
for a,b in rows:
    cells = table.add_row().cells
    cells[0].text, cells[1].text = a,b
for i,row in enumerate(table.rows):
    row.cells[0].width, row.cells[1].width = Cm(2.35), Cm(14.95)
    trpr=row._tr.get_or_add_trPr()
    trpr.append(OxmlElement('w:cantSplit'))
    for cell in row.cells:
        tcpr=cell._tc.get_or_add_tcPr()
        shade=OxmlElement('w:shd')
        shade.set(qn('w:fill'), 'E7EEEB' if i==0 else ('F4F7F5' if i%2 else 'FFFFFF'))
        tcpr.append(shade)
        margins=OxmlElement('w:tcMar')
        for side in ['top','bottom','left','right']:
            x=OxmlElement('w:'+side); x.set(qn('w:w'),'65'); x.set(qn('w:type'),'dxa'); margins.append(x)
        tcpr.append(margins)
        for p in cell.paragraphs:
            p.paragraph_format.space_after=Pt(0)
            p.paragraph_format.line_spacing=Pt(14)
            for r in p.runs:
                r.font.size=Pt(10)
                if i==0: r.bold=True

doc.add_paragraph('方案特点与验证重点', 'Heading 1')
doc.add_paragraph('个人定义表达：使用者决定手势含义，保留确认和修改权。低负担操作：少量可重复手势对应固定句子。表达忠于原意：正式播报读取已确认原句，通过动作去重和独立确认减少误触发。验收覆盖两类手势、真实建库、重启恢复、确认与取消，以及实际喇叭播报闭环。')

p=doc.add_paragraph()
p.paragraph_format.space_before=Pt(4)
r=p.add_run('当前进度  '); r.bold=True
p.add_run('板端分类器已部署，张掌已有完成事件记录，V 字尚未通过实测验收；建库面板已完成交互原型，真实采集、设备词典同步及手势触发播报仍待接入。')
for r in p.runs: r.font.size=Pt(10)

# Apply the same typeface to every visible run, including tables and symbols.
all_paragraphs = list(doc.paragraphs)
for t in doc.tables:
    for row in t.rows:
        for cell in row.cells:
            all_paragraphs.extend(cell.paragraphs)
for paragraph in all_paragraphs:
    for r in paragraph.runs:
        r.font.name = 'Microsoft YaHei'
        fonts = r._element.get_or_add_rPr().rFonts
        for attr in list(fonts.attrib):
            del fonts.attrib[attr]
        for attr in ['ascii', 'hAnsi', 'eastAsia', 'cs']:
            fonts.set(qn('w:' + attr), 'Microsoft YaHei')
doc.core_properties.title='颔语 Gesture Bridge 一页方案说明'
doc.core_properties.subject='个人词典建库与手势辅助表达'
doc.core_properties.author=''
doc.save(OUT / '颔语GestureBridge一页方案说明_更新版.docx')
print(OUT / '颔语GestureBridge一页方案说明_更新版.docx')
