import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.formats.RDFXMLDocumentFormat;
import org.semanticweb.owlapi.formats.FunctionalSyntaxDocumentFormat;
import org.semanticweb.owlapi.model.*;
import java.io.File;
public class ExportFormats { public static void main(String[] a) throws Exception {
  OWLOntologyManager m = OWLManager.createOWLOntologyManager();
  OWLOntology o = m.loadOntologyFromOntologyDocument(new File(a[0]));
  File rdf = new File(a[1]); File ofn = new File(a[2]);
  m.saveOntology(o, new RDFXMLDocumentFormat(), IRI.create(rdf));
  m.saveOntology(o, new FunctionalSyntaxDocumentFormat(), IRI.create(ofn));
  System.out.println("RDF/XML -> " + rdf.getName() + " (" + rdf.length()/1024 + " KB)");
  System.out.println("函数式   -> " + ofn.getName() + " (" + ofn.length()/1024 + " KB)");
} }
