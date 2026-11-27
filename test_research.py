import unittest

from research import grounded_facts


def grounded_response(text, ranges):
    return {'candidates': [{
        'finishReason': 'STOP',
        'content': {'parts': [{'text': text}]},
        'groundingMetadata': {
            'groundingChunks': [
                {'web': {'uri': 'https://example.com/careers', 'title': 'Public careers'}},
                {'web': {'uri': 'javascript:alert(1)', 'title': 'Invalid'}},
            ],
            'groundingSupports': [
                {'segment': {'startIndex': start, 'endIndex': end}, 'groundingChunkIndices': ids}
                for start, end, ids in ranges
            ],
        },
    }]}


class ResearchTests(unittest.TestCase):
    def test_only_retains_whole_claims_with_valid_public_sources(self):
        lines = [
            'activity|The employer operates in Abu Dhabi’s logistics sector.',
            'branch|The company opened a branch in Dubai.',
            'subsidiary|The company owns an unrelated name.',
            'hr|Contact Jane at jane@example.com.',
            'hiring|The employer announced openings last May.',
        ]
        text = '\n'.join(lines)
        ranges = []
        offset = 0
        for index, line in enumerate(lines):
            length = len(line.encode())
            if index == 0 or index == 3:
                ranges.append((offset, offset + length, [0]))
            elif index == 2:
                ranges.append((offset, offset + length, [1]))
            elif index == 4:
                ranges.append((offset, offset + length - 8, [0]))
            offset += length + 1
        facts = grounded_facts(grounded_response(text, ranges))
        self.assertEqual([fact['category'] for fact in facts], ['activity'])
        self.assertEqual(facts[0]['sources'][0]['url'], 'https://example.com/careers')

    def test_no_grounding_returns_no_facts(self):
        self.assertEqual(grounded_facts(grounded_response('NO EVIDENCE', [])), [])

    def test_incomplete_generation_fails_visibly(self):
        result = grounded_response('NO EVIDENCE', [])
        result['candidates'][0]['finishReason'] = 'MAX_TOKENS'
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            grounded_facts(result)
