import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.*;
import java.io.File;
public class LoadAll { public static void main(String[] a) {
  for (String f : a) {
    try {
      OWLOntologyManager m = OWLManager.createOWLOntologyManager();
      File file = new File(f);
      OWLOntology o = (f.toLowerCase().endsWith(".obo"))
          ? m.loadOntologyFromOntologyDocument(file)
          : m.loadOntologyFromOntologyDocument(file);
      System.out.printf("OK   %-28s 类=%-4d 对象属性=%-4d 数据属性=%-4d 个体=%-5d 公理=%d%n",
        file.getName(), o.getClassesInSignature().size(), o.getObjectPropertiesInSignature().size(),
        o.getDataPropertiesInSignature().size(), o.getIndividualsInSignature().size(), o.getAxiomCount());
    } catch (Throwable t) { System.out.println("FAIL " + new File(f).getName() + " | " + t.toString().replace("\n"," ").substring(0, Math.min(160, t.toString().length()))); }
  } } }
