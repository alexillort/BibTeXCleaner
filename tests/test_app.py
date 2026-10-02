import unittest
from unittest.mock import Mock, patch

import bibtexparser
from bibtexparser.bparser import BibTexParser
import requests

from app import app, process_bibtex, extract_arxiv_id, is_arxiv_entry, search_arxiv_by_title


class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def clean(self, content, **options):
        output, stats, log, dois = process_bibtex(content, options)
        self.assertIsNotNone(output, stats)
        parser = BibTexParser(common_strings=True)
        parser.ignore_nonstandard_types = False
        return bibtexparser.loads(output, parser=parser).entries, stats, output

    def test_page_and_assets(self):
        for path in ('/', '/static/styles.css', '/static/app.js', '/static/favicon.svg', '/health'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_invalid_payloads_return_400(self):
        for data in (None, [], {}, {'content': 5}, {'content': '  '},
                     {'content': '@article{x,title={x}}', 'options': []},
                     {'content': '@article{x,title={x}}', 'options': {'find_dois': 'yes'}},
                     {'content': '@article{x,title={x}}', 'options': {'sort_by': []}}):
            with self.subTest(data=data):
                self.assertEqual(self.client.post('/clean', json=data).status_code, 400)

    def test_invalid_bibtex_does_not_export_partial_data(self):
        for content in ('not bibtex', '@article{bad,title={oops}',
                        '@article{ok,title={Fine}}\n@article{bad,title={oops}',
                        '@article{x, title=undefinedMacro}'):
            with self.subTest(content=content):
                response = self.client.post('/clean', json={'content': content})
                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json)

    def test_basic_cleanup(self):
        entries, stats, _ = self.clean('@article{x,title={A   title},note={},year={2024}}')
        self.assertEqual(entries[0]['title'], 'A title')
        self.assertNotIn('note', entries[0])
        self.assertEqual(stats['output_entries'], 1)

    def test_sorting_is_not_overridden_by_writer(self):
        content = '@article{Z,title={Alpha},year={2020}}\n@article{A,title={Beta},year={2019}}'
        for sort, expected in [('none', ['Z', 'A']), ('title', ['Z', 'A']), ('year', ['A', 'Z'])]:
            entries, _, _ = self.clean(content, sort_by=sort)
            self.assertEqual([e['ID'] for e in entries], expected)

    def test_field_sorting_changes_output(self):
        content = '@article{x,year={2020},author={Smith},title={Alpha}}'
        _, _, ordered = self.clean(content, sort_fields=True)
        _, _, conventional = self.clean(content, sort_fields=False)
        self.assertLess(ordered.index('title ='), ordered.index('year ='))
        self.assertLess(conventional.index('author ='), conventional.index('title ='))

    def test_canonical_doi_duplicates(self):
        content = '@article{a,title={First},doi={10.1000/ABC}}\n@article{b,title={First},doi={https://doi.org/10.1000/abc}}'
        entries, stats, _ = self.clean(content, remove_duplicates=True, remove_fields='doi')
        self.assertEqual(len(entries), 1)
        self.assertEqual(stats['duplicates_removed'], 1)
        self.assertNotIn('doi', entries[0])

    def test_removing_every_field_reports_error(self):
        response = self.client.post('/clean', json={'content': '@article{x,note={Only field}}', 'options': {'remove_fields': 'note'}})
        self.assertEqual(response.status_code, 400)

    def test_key_duplicates(self):
        entries, stats, _ = self.clean('@misc{x,title={A}}\n@misc{x,title={B}}', remove_duplicates=True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['title'], 'A')

    def test_generated_keys_are_unique_with_accents_and_braces(self):
        content = '\n'.join('@article{%s,author={García, María},year={{2024}},title={The Same Title}}' % key for key in ('one', 'two', 'three'))
        entries, _, _ = self.clean(content, generate_keys=True, enclose_braces=True, remove_duplicates=True)
        self.assertEqual([e['ID'] for e in entries], ['Garcia2024Same', 'Garcia2024Same2', 'Garcia2024Same3'])

    def test_crossref_updates_when_parent_key_changes(self):
        content = '@proceedings{p,title={Conference},year={2024}}\n@inproceedings{c,title={Paper},crossref={p}}'
        entries, _, _ = self.clean(content, generate_keys=True)
        self.assertEqual(entries[1]['crossref'], entries[0]['ID'])

    def test_crossref_updates_when_duplicate_parent_is_removed(self):
        content = '@proceedings{p,doi={10.1/test}}\n@proceedings{q,doi={10.1/test}}\n@inproceedings{c,title={Paper},crossref={q}}'
        entries, _, _ = self.clean(content, remove_duplicates=True)
        self.assertEqual(entries[1]['crossref'], 'p')

    def test_add_fields_cannot_replace_structural_keys(self):
        for field in ('ID=hacked', 'ENTRYTYPE=misc', 'note=bad}', 'oops'):
            with self.subTest(field=field):
                response = self.client.post('/clean', json={'content': '@article{x,title={Hi}}', 'options': {'add_fields': field}})
                self.assertEqual(response.status_code, 400)

    def test_added_fields_support_commas_and_do_not_overwrite(self):
        entries, _, _ = self.clean('@article{x,title={Hi},note={Keep}}', add_fields='note=Replace, "keywords=one, two", language=spanish')
        self.assertEqual(entries[0]['note'], 'Keep')
        self.assertEqual(entries[0]['keywords'], 'one, two')

    def test_title_protection_does_not_corrupt_author_doi_or_crossref(self):
        content = '@article{x,title={NASA},author={Doe, Jane and Smith, John},doi={10.1/a},crossref={p}}'
        entries, _, _ = self.clean(content, enclose_braces=True)
        self.assertEqual(entries[0]['title'], '{NASA}')
        self.assertEqual(entries[0]['author'], 'Doe, Jane and Smith, John')
        self.assertEqual(entries[0]['doi'], '10.1/a')
        self.assertEqual(entries[0]['crossref'], 'p')

    def test_arxiv_identifiers_and_no_false_positive_from_unrelated_url(self):
        for value, expected in [('https://arxiv.org/abs/1706.03762v2', '1706.03762'),
                                ('10.48550/arXiv.1706.03762', '1706.03762'),
                                ('https://arxiv.org/abs/math.GT/0309136v1', 'math.GT/0309136')]:
            self.assertEqual(extract_arxiv_id(value), expected)
        self.assertEqual(is_arxiv_entry({'url': 'https://example.org/1234.56789'}), (None, None))

    @patch('app.requests.get')
    def test_arxiv_id_works_offline_before_fields_are_removed(self, get):
        entries, stats, _ = self.clean('@misc{x,title={Attention},eprint={1706.03762v2}}', find_dois=True, remove_fields='eprint')
        self.assertEqual(entries[0]['doi'], '10.48550/arXiv.1706.03762')
        self.assertNotIn('eprint', entries[0])
        get.assert_not_called()

    @patch('app.requests.get')
    def test_doi_lookup_not_enabled_by_default(self, get):
        self.clean('@article{x,title={Hi}}')
        get.assert_not_called()

    @patch('app.requests.get', side_effect=requests.Timeout)
    def test_network_failure_preserves_output(self, get):
        entries, stats, _ = self.clean('@article{x,title={Hi}}', find_dois=True)
        self.assertEqual(entries[0]['title'], 'Hi')
        self.assertEqual(stats['dois_found'], 0)
        self.assertEqual(stats['dois_searched'], 1)

    @patch('app.requests.get')
    def test_crossref_requires_matching_author(self, get):
        response = Mock()
        response.json.return_value = {'message': {'items': [{'title': ['My Article'], 'DOI': '10.1/a', 'author': [{'family': 'Smith'}]}]}}
        get.return_value = response
        entries, _, _ = self.clean('@article{x,title={My Article},author={Doe, Jane}}', find_dois=True)
        self.assertNotIn('doi', entries[0])
        entries, _, _ = self.clean('@article{x,title={My Article},author={Smith, Jane}}', find_dois=True)
        self.assertEqual(entries[0]['doi'], '10.1/a')

    @patch('app.time.sleep')
    @patch('app.requests.get')
    def test_arxiv_atom_response(self, get, sleep):
        response = Mock()
        response.content = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Search</title><entry><id>https://arxiv.org/abs/1706.03762v5</id><title>Attention Is All You Need</title></entry></feed>'
        get.return_value = response
        identifier, _ = search_arxiv_by_title('Attention Is All You Need')
        self.assertEqual(identifier, '1706.03762')
        self.assertEqual(get.call_args.args[0], 'https://export.arxiv.org/api/query')

    def test_metadata_and_unicode_roundtrip(self):
        content = '@string{venue="Revista"}\n@preamble{"Test"}\n@comment{Keep me}\n@custom{x,author={García, María},journal=venue,title={\\LaTeX{} y {NASA}}}'
        entries, _, output = self.clean(content)
        self.assertEqual(entries[0]['author'], 'García, María')
        self.assertEqual(entries[0]['journal'], 'Revista')
        self.assertIn('Keep me', output)
        self.assertIn('@preamble', output)
        self.assertEqual(entries[0]['title'], r'\LaTeX{} y {NASA}')

    def test_request_limit_returns_json(self):
        with patch.dict(app.config, MAX_CONTENT_LENGTH=50):
            response = self.client.post('/clean', json={'content': 'x' * 100})
        self.assertEqual(response.status_code, 413)
        self.assertIn('error', response.json)


if __name__ == '__main__':
    unittest.main()
