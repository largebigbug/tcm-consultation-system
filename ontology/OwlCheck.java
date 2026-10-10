import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.*;

import java.io.File;
import java.util.*;

/** 用 WebProtege 自带的 OWLAPI 4.5.13 加载本体，验证可导入性并统计规模（4.5 老 API 写法）。 */
public class OwlCheck {
    public static void main(String[] args) throws Exception {
        OWLOntologyManager m = OWLManager.createOWLOntologyManager();
        OWLOntology o = m.loadOntologyFromOntologyDocument(new File(args[0]));
        IRI iri = null;
        try { iri = o.getOntologyID().getOntologyIRI().orNull(); } catch (Throwable ignore) { }
        System.out.println("解析成功 -> ontologyIRI = " + iri);

        int cls = 0;
        for (OWLClass c : o.getClassesInSignature()) { if (!c.isOWLThing()) cls++; }
        int op = 0;
        for (OWLObjectProperty p : o.getObjectPropertiesInSignature()) { if (!p.isOWLTopObjectProperty()) op++; }
        int dp = 0;
        for (OWLDataProperty p : o.getDataPropertiesInSignature()) { if (!p.isOWLTopDataProperty()) dp++; }
        int ind = o.getIndividualsInSignature().size();
        System.out.println("类=" + cls + " 对象属性=" + op + " 数据属性=" + dp + " 个体=" + ind
                + " 公理=" + o.getAxiomCount());

        String[] want = {"Patient", "Herb", "Prescription", "Enum_PULSE", "Role_ROLE_01",
                         "Flow_FLOW_VISIT_001", "Screen_frmPatientCreate", "assoc_ASSOC_PATIENT_VISIT"};
        List<String> missing = new ArrayList<String>();
        for (String w : want) {
            IRI i = IRI.create("http://hermes.local/tcm-ontology#" + w);
            boolean ok = o.containsClassInSignature(i) || o.containsObjectPropertyInSignature(i)
                    || o.containsDataPropertyInSignature(i) || o.containsIndividualInSignature(i);
            if (!ok) missing.add(w);
            System.out.println("  抽查 " + w + " -> " + (ok ? "在位" : "缺失"));
        }

        int zh = 0;
        Set<String> samples = new TreeSet<String>();
        for (OWLAnnotationAssertionAxiom ax : o.getAxioms(AxiomType.ANNOTATION_ASSERTION)) {
            if (!ax.getProperty().isLabel()) continue;
            OWLAnnotationValue v = ax.getValue();
            if (v instanceof OWLLiteral && "zh".equals(((OWLLiteral) v).getLang())) {
                zh++;
                if (samples.size() < 8) samples.add(((OWLLiteral) v).getLiteral());
            }
        }
        System.out.println("中文标签数 = " + zh + " | 样例: " + samples);
        System.out.println(missing.isEmpty() ? "结论：文件可被 WebProtege 正常加载 OK" : "结论：抽查缺失 " + missing);
    }
}
