import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer
from pathlib import Path

chunks_csv = pd.read_csv("C:/Users/djeto/Desktop/Projet-Elisa/data/processed/chunks.csv")
output = Path("C:/Users/djeto/Desktop/Projet-Elisa/models")
output.mkdir(parents=True, exist_ok=True)

metadata_csv = chunks_csv.drop(columns=["text"]) #on récupère les méta données du csv: project_id, chunk_id, flag_type, event, time_to_event, doc_date
metadata_csv.to_pickle(output / "chunks_metadata.pkl") #stocker les métadata pour récupérer on fera metadata = pd.read_pickle("output/chunks_metadata.pkl")



#récupérer les textes que l'on va encoder
texte = chunks_csv["text"].tolist()

#encodage
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
embeddings = model.encode(texte)

norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
embeddings_normalized = embeddings / norms #on normalise nos vecteurs afin d'avoir des trucs comparables
np.save(output / "embeddings.npy", embeddings_normalized) #le format npy permet de stocker le fichier tel quel, d'éviter les conversions inutiles et donc optimiser les calculs et la mémoire



#tests
test_1 = model.encode([
    "project affected households; - the key impacts of land acquisition; - assessment of compensation for acquired land; - framework for mitigation of identified impacts; - key grievances of PAHs; and - actions being implemented by the company to address these grievances. The company will ensure that impacts on account of land acquisition are managed in accordance with PS5 provisions. - PS6: Biodiversity Conservation and Sustainable Natural Resource Management A seawater (for once through condenser cooling) intake open channel (80 m width at base at 3 m below chart datum) is proposed in the Kotdi creek and an outfall/discharge channel (60 m base width at 1 m below chart datum) is proposed in the Mudhwa creek. The seawater intake required is a maximum of 594,200 m3/hr, and the channel is designed for 620,000 m3/hr. Construction of the channel and regular upkeep will involve capital and maintenance dredging. Capital dredging is expected to generate as much as 4.1 million m3 of dredge spoil. The company will, within a timeframe agreed with IFC, based on recommendations of a",
    "waste, and that it is likely that it will either have to be shipped to Ghana, Western Europe or another destination for treatment. Liquid Waste Management: a storm water drainage system will be designed allowing surface run-off water to pass through oil/water separators prior to discharge into the port basin. Outlets to the basin shall be closable. Terminal waste water from the office buildings shall be collected and treated in a septic tank with 3 compartments. Liquids will be drained-off to buried pipes discharging into the port basin and solids shall be removed at regular intervals. Waste water from the workshop, fuel station and washing bay shall pass dedicated separators with run-off to the drainage system. Hazardous materials (such as flammable gases and liquids, corrosives, oxidizing substances etc): the Terminal design indicates a dedicated and separate area for the storage of dangerous products. The area will have a secondary containment in compliance with the requirements of the International Maritime Organization - International Convention for the Prevention of Pollution from Ships”. Soil and groundwater contamination: The"]
)

test_1_normalized = test_1/np.linalg.norm(test_1,  axis=1, keepdims=True)
# Similarité entre les deux textes de test
similarity = np.dot(test_1_normalized[0], test_1_normalized[1])
print(f"Similarity entre les 2 textes de test: {similarity:.4f}")
print(f"Shape des embeddings du corpus: {embeddings.shape}")
print(f"Shape d'un vecteur: {embeddings[0].shape}")