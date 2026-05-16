import os
import json
from google import genai
from google.genai import types

def suggest_mapping(layers: list, colors: list, direction: str = "to-jww") -> dict:
    """
    Uses Gemini API to suggest layer and color mappings based on source layer names.
    Supports both DWG->JWW and JWW->DWG directions.
    Falls back to a mock rule-based suggestion if API key is not set or API fails.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not found. Using local mock AI suggestion.")
        return _mock_suggestion(layers, direction)
    
    try:
        client = genai.Client(api_key=api_key)
        
        if direction == "to-jww":
            prompt = f"""
            You are an AI mapping DWG/DXF AutoCAD layers to Jw_cad (JWW) layers.
            In Jw_cad, standard layer groups are 0 to F, and layers are 0 to F. 
            Usually elements go to:
            0: Guidelines, Reference, Default
            1: Walls, Columns
            2: Doors, Windows
            3: Texts, Dimensions
            
            Given DXF layers: {layers}
            And colors: {colors}
            
            Provide JSON:
            {{ "layer_mapping": {{ "DXF_LAYER": "JWW_LAYER_NUMBER" }}, "color_mapping": {{ "DXF_COLOR": "JWW_COLOR_NUMBER (1-9)" }} }}
            JWW layer numbers should be single characters '0'-'9' or 'A'-'F'.
            JWW color numbers are '1'-'9' (2 is black/white).
            Return ONLY valid JSON.
            """
        else:
            prompt = f"""
            You are an AI mapping Jw_cad (JWW) exported DXF layers/colors to standard AutoCAD (DWG) format.
            JWW layers are usually named '0'-'F' or '0-1'.
            Standard DWG layers (AIA CAD Standard) include:
            'A-WALL' (Walls), 'A-DOOR' (Doors), 'A-GLAZ' (Windows), 'A-ANNO-TEXT' (Text), 'A-ANNO-DIMS' (Dimensions), '0' (Default).
            
            Given JWW layers: {layers}
            And JWW colors: {colors}
            
            Provide JSON:
            {{ "layer_mapping": {{ "JWW_LAYER": "STANDARD_DWG_LAYER" }}, "color_mapping": {{ "JWW_COLOR": "STANDARD_DWG_COLOR (e.g. 256 for BYLAYER, 1 for Red)" }} }}
            For colors, default to '256' (BYLAYER) unless it's a specific highlighted color.
            Return ONLY valid JSON.
            """
            
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return json.loads(response.text)
        
    except Exception as e:
        print(f"AI Suggestion error: {e}")
        return _mock_suggestion(layers, direction)

def _mock_suggestion(layers: list, direction: str) -> dict:
    layer_map = {}
    for l in layers:
        ln = str(l).lower()
        if direction == "to-jww":
            if 'wall' in ln or 'col' in ln: layer_map[l] = "1"
            elif 'dim' in ln or 'text' in ln: layer_map[l] = "3"
            elif 'door' in ln or 'window' in ln or 'glaz' in ln: layer_map[l] = "2"
            else: layer_map[l] = "0"
        else:
            if ln == '1' or ln == '1-0': layer_map[l] = "A-WALL"
            elif ln == '2' or ln == '2-0': layer_map[l] = "A-DOOR"
            elif ln == '3' or ln == '3-0': layer_map[l] = "A-ANNO-TEXT"
            else: layer_map[l] = "0"
            
    return {"layer_mapping": layer_map, "color_mapping": {}}
