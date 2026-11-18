"""Geometry-based text order proposals inside supplied panels, with raw output retained."""
from copy import deepcopy

def propose_text_order(page,tolerance=.01):
    """Group overlapping vertical text bands; read bands downwards, each band RTL.

    This is a proposal for conventional horizontal manga balloon groups. It does
    not determine panel order or resolve overlapping/spanning/diagonal layouts.
    Region quality and speaker attribution still require independent review.
    """
    result=deepcopy(page);changes=[]
    for pi,panel in enumerate(result['panels']):
        texts=panel['texts'];bands=[]
        for i,block in sorted(enumerate(texts),key=lambda pair:pair[1]['region'][1]):
            x,y,w,h=block['region']
            if w<=0 or h<=0 or not (0<=x<=1 and 0<=y<=1 and x+w<=1.001 and y+h<=1.001):raise ValueError('Order proposals require valid normalized regions')
            if bands and y<=bands[-1]['bottom']+tolerance:
                bands[-1]['items'].append((i,block));bands[-1]['bottom']=max(bands[-1]['bottom'],y+h)
            else:bands.append({'bottom':y+h,'items':[(i,block)]})
        ordered=[pair for band in bands for pair in sorted(band['items'],key=lambda pair:-(pair[1]['region'][0]+pair[1]['region'][2]/2))]
        indexes=[i for i,_ in ordered]
        if indexes!=list(range(len(texts))):changes.append({'panel_index':pi,'old_indexes_in_proposed_order':indexes,'requires_visual_review':True})
        panel['texts']=[block for _,block in ordered]
    return result,changes
